from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from gemini import GPTClient
from models import AssistantMessage, Conversation, Role, SystemMessage, UserMessage, RateLimitException
from speech import SpeechClient
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ExtBot
from typing import TypedDict, cast, final
from uuid import uuid4
from db import Database
import time
import os

@dataclass
class ConversationMode:
  title: str
  prompt: str
  id: str = field(default_factory=lambda: str(uuid4()))

class ChatData(TypedDict):
  conversations: dict[int, Conversation]
  modes: dict[str, ConversationMode]
  current_mode_id: str|None

@dataclass
class ChatState:
  timeout_task: asyncio.Task|None = None
  current_conversation: Conversation|None = None

  new_mode_title: str|None = None
  editing_mode: ConversationMode|None = None

@dataclass
class ChatContext:
  chat_id: int
  chat_state: ChatState
  __chat_data: ChatData

  @property
  def all_conversations(self) -> dict[int, Conversation]:
    if 'conversations' not in self.__chat_data:
      self.__chat_data['conversations'] = {}
    return self.__chat_data['conversations']

  @property
  def modes(self) -> dict[str, ConversationMode]:
    if 'modes' not in self.__chat_data:
      self.__chat_data['modes'] = {}
    return self.__chat_data['modes']

  @property
  def current_mode(self) -> ConversationMode|None:
    current_mode_id = self.__chat_data.get('current_mode_id')
    if not current_mode_id:
      return None
    return self.modes.get(current_mode_id)

  def get_conversation(self, conversation_id: int) -> Conversation|None:
    if 'conversations' not in self.__chat_data:
      self.__chat_data['conversations'] = {}
    return self.__chat_data['conversations'].get(conversation_id)

  def add_mode(self, mode: ConversationMode):
    if 'modes' not in self.__chat_data:
      self.__chat_data['modes'] = {}
    self.__chat_data['modes'][mode.id] = mode

  def set_current_mode(self, mode: ConversationMode|None):
    self.__chat_data['current_mode_id'] = mode.id if mode else None

TELEGRAM_MAX_MESSAGE_LENGTH = 4096 # Telegram's actual limit
# Define default throttle interval
DEFAULT_EDIT_THROTTLE_INTERVAL_SECONDS = 0.5

class ChatManager:
  def __init__(self, *, gpt: GPTClient, speech: SpeechClient|None, bot: ExtBot, 
               context: ChatContext, conversation_timeout: int|None, db: Database, 
               start_message: str):
    self.__gpt = gpt
    self.__speech = speech
    self.bot = bot
    self.context = context
    self.__conversation_timeout = conversation_timeout
    self.db = db
    self.start_message = start_message
    # Get throttle interval from env var or use default
    try:
        self.__edit_throttle_interval = float(os.environ.get('TELEGRAM_GPT_EDIT_THROTTLE_INTERVAL', DEFAULT_EDIT_THROTTLE_INTERVAL_SECONDS))
    except ValueError:
        self.__edit_throttle_interval = DEFAULT_EDIT_THROTTLE_INTERVAL_SECONDS
    logging.info(f"Using Telegram edit throttle interval: {self.__edit_throttle_interval}s")

  async def new_conversation(self):
    chat_state = self.context.chat_state
    timeout_job = chat_state.timeout_task
    if timeout_job:
      timeout_job.cancel()
      chat_state.timeout_task = None
    await self.__expire_current_conversation()

    current_mode = self.context.current_mode
    if current_mode:
      text = f"Started a new conversation in mode \"{current_mode.title}\"."
    else:
      text = "Started a new conversation."
      #text = "Started a new conversation without mode. Send /mode to create a new mode."

    #reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("Change mode", callback_data="/mode")]])
    #await self.bot.send_message(chat_id=self.context.chat_id, text=text, reply_markup=reply_markup)
    await self.bot.send_message(chat_id=self.context.chat_id, text=text)

    logging.info(f"Started a new conversation for chat {self.context.chat_id}")

  async def __create_conversation(self, user_message: UserMessage) -> Conversation:
      # Create a new conversation record in PostgreSQL.
      db_conv = await self.db.create_conversation(self.context.chat_id)
      # Save the initial user message.
      await self.db.add_message(user_message.id, db_conv.id, user_message.role, user_message.content)
      # Create an in-memory conversation representation.
      conversation = Conversation(id=db_conv.id, title=None, started_at=user_message.timestamp, messages=[user_message])
      return conversation
    
  async def handle_message(self, *, text: str, user_message_id: int):
    sent_message = await self.bot.send_message(chat_id=self.context.chat_id, text="Generating response...")

    user_message = UserMessage(user_message_id, text)

    conversation = self.context.chat_state.current_conversation
    if conversation:
      conversation.messages.append(user_message)
      await self.db.add_message(user_message.id, conversation.id, user_message.role, user_message.content)
    else:
      conversation = await self.__create_conversation(user_message)

    await self.__complete(conversation, sent_message.id)

    return conversation

  async def handle_audio(self, *, audio: bytearray, user_message_id: int):
    chat_id = self.context.chat_id
    if not self.__speech:
      await self.bot.send_message(chat_id=chat_id, text="Speech recognition is not available for this chat.")
      return

    sent_message = await self.bot.send_message(chat_id=chat_id, text="Recognizing audio...", reply_to_message_id=user_message_id)

    try:
      text = await self.__speech.speech_to_text(audio=audio, message_id=f'{chat_id}_{user_message_id}')
    except Exception as e:
      await self.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.id, text="Could not recognize audio")
      logging.warning(f"Could not recognize audio for chat {chat_id}: {e}")
      return

    logging.info(f"Recognized audio: \"{text}\" for chat {chat_id}")

    if not text:
      await self.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.id, text="Could not recognize audio")
      return

    await self.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.id, text=f"You said: \"{text}\"")
    conversation = await self.handle_message(text=text, user_message_id=user_message_id)

    if not conversation.last_message or not conversation.last_message.role == Role.ASSISTANT:
      return

    await self.__read_out_message(cast(AssistantMessage, conversation.last_message))

  async def retry_last_message(self):
    chat_id = self.context.chat_id
    conversation = self.context.chat_state.current_conversation
    if not conversation:
      await self.bot.send_message(chat_id=chat_id, text="No conversation to retry")
      return
      
    sent_message = await self.bot.send_message(chat_id=chat_id, text="Regenerating response...")

    if conversation.last_message and conversation.last_message.role == Role.ASSISTANT:
      conversation.messages.pop()

    if not conversation.last_message or not conversation.last_message.role == Role.USER:
      await self.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.id, text="No message to retry")
      return

    await self.__complete(conversation, sent_message.id)

  async def resume(self, *, conversation_id: int):
    chat_id = self.context.chat_id
    conversation = Conversation.from_db_model(await self.db.get_conversation(conversation_id))
    if not conversation:
      await self.bot.send_message(chat_id=chat_id, text="Failed to find that conversation. Try sending a new message.")
      return

    current_mode = self.context.current_mode
    mode_description = f" in mode \"{current_mode.title}\"" if current_mode else ""
    text = f"Resuming conversation \"{conversation.title}\"{mode_description}: "
    sent_message = await self.bot.send_message(chat_id=chat_id, text=text)

    last_message = conversation.last_message
    logging.info(f"last_message {last_message}")
    if last_message:
      await self.bot.edit_message_text(chat_id=chat_id, 
                                       message_id=sent_message.id, 
                                       text=text + last_message.content)

    self.context.chat_state.current_conversation = conversation
    await self.db.update_active_conversation(chat_id, conversation.id)
    self.__add_timeout_task()

    logging.info(f"Resumed conversation {conversation.id} for chat {chat_id}")

  async def show_conversation_history(self):
    conversations = await self.db.list_conversations_by_chat_id(self.context.chat_id)
    text = '\n'.join(f"[/resume_{conversation.id}] {conversation.title} ({conversation.started_at:%Y-%m-%d %H:%M})" for conversation in conversations)

    if not text:
      text = "No conversation history"

    logging.info(f"Sending history for chat {self.context.chat_id}: {text}")

    await self.bot.send_message(chat_id=self.context.chat_id, text=text)

    logging.info(f"Showed conversation history for chat {self.context.chat_id}")

  async def read_out_message(self, *, message_id: int):
    chat_id = self.context.chat_id

    current_conversation = self.context.chat_state.current_conversation
    if not current_conversation:
      await self.bot.send_message(chat_id=chat_id, text="Can only read out messages in current conversation.")
      return

    message = next((message for message in current_conversation.messages if message.id == message_id), None)
    if not message:
      await self.bot.send_message(chat_id=chat_id, text="Could not find that message.")
      return

    if message.role != Role.ASSISTANT:
      await self.bot.send_message(chat_id=chat_id, text="Can only read out messages sent by the bot.")
      return

    await self.__read_out_message(cast(AssistantMessage, message))

  async def list_modes_for_selection(self):
    modes = list(self.context.modes.values())

    if modes:
      current_mode = self.context.current_mode
      text = f"Current mode: \"{current_mode.title}\". Change to mode:" if current_mode else "Select a mode:"
    else:
      text = "No modes available. Tap \"Add\" to create a new mode."

    action_buttons = [[InlineKeyboardButton("Clear", callback_data="/mode_clear"), InlineKeyboardButton("Add", callback_data="/mode_add"), InlineKeyboardButton("Show", callback_data="/mode_show")]]
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton(mode.title, callback_data=f"/mode_select_{mode.id}")] for mode in modes] + action_buttons)
    await self.bot.send_message(chat_id=self.context.chat_id, text=text, reply_markup=reply_markup)

  async def select_mode(self, mode_id: str|None, sent_message_id: int):
    if not mode_id:
      self.context.set_current_mode(None)
      await self.bot.edit_message_text(chat_id=self.context.chat_id, message_id=sent_message_id, text="Cleared mode.")
      return

    mode = self.context.modes.get(mode_id)
    if not mode:
      await self.bot.send_message(chat_id=self.context.chat_id, text="Failed to find that mode. Try sending a new message.")
      return

    self.context.set_current_mode(mode)

    text = f"Changed mode to \"{mode.title}\"."
    await self.bot.edit_message_text(chat_id=self.context.chat_id, message_id=sent_message_id, text=text)

    logging.info(f"Selected mode {mode.id} for chat {self.context.chat_id}")

  async def update_mode_title(self, title: str) -> bool:
    self.context.chat_state.new_mode_title = title
    return True

  async def add_or_edit_mode(self, prompt: str):
    editing_mode = self.context.chat_state.editing_mode
    if editing_mode:
      editing_mode.prompt = prompt
      self.context.chat_state.editing_mode = None

      await self.bot.send_message(chat_id=self.context.chat_id, text="Mode updated.")
    else:
      title = self.context.chat_state.new_mode_title
      self.context.chat_state.new_mode_title = None
      if not title:
        raise Exception("Invalid state")

      mode = ConversationMode(title, prompt)
      self.context.add_mode(mode)

      if not self.context.current_mode:
        self.context.set_current_mode(mode)

      await self.bot.send_message(chat_id=self.context.chat_id, text="Mode added.")

  async def show_modes(self):
    modes = self.context.modes.values()
    if modes:
      text = "Select a mode to edit:"
      reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton(mode.title, callback_data=f"/mode_detail_{mode.id}")] for mode in modes])
      await self.bot.send_message(chat_id=self.context.chat_id, text=text, reply_markup=reply_markup)
    else:
      text = "No modes defined. Send /mode to add a new mode."
      await self.bot.send_message(chat_id=self.context.chat_id, text=text)

    logging.info(f"Showed modes for chat {self.context.chat_id}")

  async def show_mode_detail(self, id: str):
    mode = self.context.modes.get(id)
    if not mode:
      await self.bot.send_message(chat_id=self.context.chat_id, text="Invalid mode.")
      return

    text = f"Mode \"{mode.title}\":\n{mode.prompt}"
    reply_markup = InlineKeyboardMarkup([
                                          [InlineKeyboardButton('Edit', callback_data=f"/mode_edit_{mode.id}"), InlineKeyboardButton('Delete', callback_data=f"/mode_delete_{mode.id}")],
                                        ])
    await self.bot.send_message(chat_id=self.context.chat_id, text=text, reply_markup=reply_markup)

  async def edit_mode(self, id: str) -> bool:
    mode = self.context.modes.get(id)
    if not mode:
      await self.bot.send_message(chat_id=self.context.chat_id, text="Invalid mode.")
      return False

    self.context.chat_state.editing_mode = mode

    await self.bot.send_message(chat_id=self.context.chat_id, text=f"Enter a new prompt for mode \"{mode.title}\":")
    return True

  async def delete_mode(self, id: str, sent_message_id: int):
    mode = self.context.modes.get(id)
    if not mode:
      await self.bot.send_message(chat_id=self.context.chat_id, text="Invalid mode.")
      return

    del self.context.modes[mode.id]

    text = f"Mode \"{mode.title}\" deleted."
    await self.bot.edit_message_text(chat_id=self.context.chat_id, message_id=sent_message_id, text=text)

  async def __complete(self, conversation: Conversation, sent_message_id: int):
      chat_id = self.context.chat_id
      assistant_message = None
      accumulated_content = ""
      last_edit_time = 0
      initial_db_add_done = False # Flag for initial DB add

      try:
          system_prompt = None
          if self.context.current_mode:
              system_prompt = SystemMessage(self.context.current_mode.prompt)

          async for chunk_message in self.__gpt.complete(conversation, conversation.messages[-1], sent_message_id, system_prompt):
              accumulated_content = chunk_message.content # Assumes chunk_message has cumulative content

              if not assistant_message:
                  assistant_message = AssistantMessage(chunk_message.id, '', chunk_message.replied_to_id)
                  # Add to conversation object immediately if needed elsewhere,
                  # but primary state is now accumulated_content
                  # conversation.messages.append(assistant_message) # Optional: only if needed before stream ends

                  # Initial DB add with empty content
                  await self.db.add_message(
                      assistant_message.id, conversation.id, assistant_message.role.value, ''
                  )
                  initial_db_add_done = True

              # --- Throttled Telegram Edit ---
              current_time = time.monotonic()
              if current_time - last_edit_time > self.__edit_throttle_interval:
                  # Update the in-memory message object's content *before* displaying
                  # This ensures the truncation logic later uses the most recent content
                  if assistant_message: # Check if assistant_message exists
                        assistant_message.content = accumulated_content

                  display_limit = TELEGRAM_MAX_MESSAGE_LENGTH - 50 # Leave buffer
                  display_text = (
                      accumulated_content[:display_limit] + '...\n\nGenerating...'
                      if len(accumulated_content) > display_limit
                      else accumulated_content + '\n\nGenerating...'
                  )
                  try:
                      print(f"text: {display_text}")
                      await self.bot.edit_message_text(
                          chat_id=chat_id, message_id=sent_message_id, text=display_text
                      )
                      last_edit_time = current_time
                  except Exception as edit_err:
                      logging.warning(f"Non-fatal error editing message during stream for chat {chat_id} (msg_id: {sent_message_id}): {edit_err}")
                      # Prevent rapid retries on persistent edit errors
                      last_edit_time = current_time

          # --- Stream finished ---

          if assistant_message:
              # Ensure the in-memory message object has the final accumulated content
              assistant_message.content = accumulated_content

              if assistant_message not in conversation.messages: # Avoid duplicates if logic changes later
                conversation.messages.append(assistant_message)

              # --- Final DB Update & Telegram Edit ---
              final_text_for_display_and_db = accumulated_content # Start with full content

              # Apply truncation logic if needed
              if len(accumulated_content) > TELEGRAM_MAX_MESSAGE_LENGTH:
                  # Define suffix clearly
                  truncation_suffix = "...\n\n(Type \"continue\" to view more.)"
                  # Calculate max length for the content part
                  max_content_len = max(0, TELEGRAM_MAX_MESSAGE_LENGTH - len(truncation_suffix))
                  # Truncate content
                  truncated_content = accumulated_content[:max_content_len]
                  # TODO: (Optional Future Improvement) Implement smarter truncation (e.g., word boundary)
                  final_text_for_display_and_db = truncated_content + truncation_suffix

              # Update DB *once* with the final text (truncated or full)
              await self.db.update_message(assistant_message.id, final_text_for_display_and_db)

              # Final Telegram Edit: Show the final message without "Generating..."
              try:
                  await self.bot.edit_message_text(
                      chat_id=chat_id,
                      message_id=sent_message_id,
                      text=final_text_for_display_and_db # Send the final, potentially truncated, text
                  )
                  logging.info(f"Replied chat {chat_id} with final message length {len(final_text_for_display_and_db)}")
              except Exception as final_edit_err:
                  # Log error if the final edit fails, but proceed (DB is already updated)
                  logging.error(f"Error performing final edit for chat {chat_id} (msg_id: {sent_message_id}): {final_edit_err}")
                  # User might see last "Generating..." message, but DB is correct.

      except TimeoutError:
          # Handle timeout specifically
          logging.warning(f"Timeout generating response for chat {chat_id} (msg_id: {sent_message_id})")
          retry_markup = InlineKeyboardMarkup([[InlineKeyboardButton('Retry', callback_data='/retry')]])
          try:
              await self.bot.edit_message_text(chat_id=chat_id, message_id=sent_message_id, text="Generation timed out.", reply_markup=retry_markup)
          except Exception as e_timeout_edit:
                logging.error(f"Error sending timeout message for chat {chat_id}: {e_timeout_edit}")
      except RateLimitException as e_rate_limit:
          # Handle the common Rate Limit Error
          # Log the specific underlying error if available
          original_err_msg = f" (Original: {e_rate_limit.original_exception})" if e_rate_limit.original_exception else ""
          logging.warning(f"API Rate limit/quota exceeded for chat {chat_id} (msg_id: {sent_message_id}): {e_rate_limit}{original_err_msg}")
          try:
              # Inform the user politely
              await self.bot.edit_message_text(
                  chat_id=chat_id,
                  message_id=sent_message_id,
                  text="⏳ The bot is currently busy or has reached a usage limit. Please try again in a few moments."
              )
          except Exception as e_quota_edit:
                logging.error(f"Error sending rate limit error message for chat {chat_id}: {e_quota_edit}")      
      except Exception as e:
          # General error handling for the stream/completion process
          logging.exception(f"Error generating response for chat {chat_id} (msg_id: {sent_message_id}): {e}")
          retry_markup = InlineKeyboardMarkup([[InlineKeyboardButton('Retry', callback_data='/retry')]])
          try:
              # Avoid sending overly detailed errors to the user
              await self.bot.edit_message_text(chat_id=chat_id, message_id=sent_message_id, text="Sorry, an error occurred.", reply_markup=retry_markup)
          except Exception as e_generic_edit:
                logging.error(f"Error sending generic error message for chat {chat_id}: {e_generic_edit}")

      # Ensure current conversation is set even if errors occurred before title generation
      self.context.chat_state.current_conversation = conversation
      self.__add_timeout_task()

  async def __read_out_message(self, message: AssistantMessage):
    chat_id = self.context.chat_id

    if not self.__speech:
      await self.bot.send_message(chat_id=chat_id, text="Speech recognition is not available for this chat.")
      return

    logging.info(f"Generating audio for chat {chat_id} for message \"{message.content}\"")

    try:
      sent_message = await self.bot.send_message(chat_id=chat_id, text="Generating audio...", reply_to_message_id=message.id)
      speech_content = await self.__speech.text_to_speech(text=message.content)
    except Exception as e:
      await self.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.id, text="Could not generate audio")
      logging.warning(f"Could not generate audio for chat {chat_id}: {e}")
      return
    finally:
      await self.bot.delete_message(chat_id=chat_id, message_id=sent_message.id)
      await self.bot.send_voice(chat_id=chat_id, voice=speech_content, reply_to_message_id=message.id)

  def __add_timeout_task(self):
    chat_state = self.context.chat_state
    last_task = chat_state.timeout_task
    if last_task:
      last_task.cancel()
      chat_state.timeout_task = None

    timeout = self.__conversation_timeout
    if not timeout:
      return

    async def time_out_current_conversation():
      await asyncio.sleep(timeout)
      chat_state.timeout_task = None

      await self.__expire_current_conversation()

    chat_state.timeout_task = asyncio.create_task(time_out_current_conversation())

  async def __expire_current_conversation(self):
    chat_state = self.context.chat_state
    current_conversation = chat_state.current_conversation
    if not current_conversation:
      return

    chat_state.current_conversation = None

    last_message = current_conversation.last_message
    if not last_message or last_message.role != Role.ASSISTANT:
      return
    last_message = cast(AssistantMessage, last_message)

    new_text = last_message.content + f"\n\nThis conversation has expired and it was about \"{current_conversation.title}\". A new conversation has started."
    resume_markup = InlineKeyboardMarkup([[InlineKeyboardButton("Resume this conversation", callback_data=f"/resume_{current_conversation.id}")]])
    await self.bot.edit_message_text(chat_id=self.context.chat_id, message_id=last_message.id, text=new_text, reply_markup=resume_markup)

    logging.info(f"Conversation {current_conversation.id} timed out")

#  def __create_conversation(self, user_message: UserMessage) -> Conversation:
#    current_conversation = self.context.chat_state.current_conversation
#    if current_conversation:
#      current_conversation.messages.append(user_message)
#      return current_conversation
#    else:
#      conversations = self.context.all_conversations
#      conversation = self.__gpt.new_conversation(len(conversations), user_message)
#      conversations[conversation.id] = conversation
#
#      return conversation
