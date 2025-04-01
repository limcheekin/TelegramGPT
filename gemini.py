import asyncio
from dataclasses import dataclass, field
import logging
from typing import AsyncGenerator, cast
from google import genai
from google.genai import types
from models import AssistantMessage, Conversation, Message, SystemMessage, UserMessage
from google.api_core import exceptions as google_exceptions
from models import RateLimitException
from db import Database

@dataclass
class GPTOptions:
    api_key: str = field(repr=False)
    model_name: str = 'gemini-1.5-flash-002' # 'gemini-2.0-flash-001' doesn't support prompt caching yet
    max_message_count: int | None = None
    system_message: str | None = None
    context_file: str | None = None
    db: Database | None = None

class GPTClient:
    def __init__(self, *, options: GPTOptions):
        self.__model_name = options.model_name
        self.__max_message_count = options.max_message_count
        self.__system_message = options.system_message
        self.__file = options.context_file
        self.__db = options.db
        if self.__db is None:
             # Handle cases where db might not be provided if necessary
             # For this use case, assume it's required for title saving
             raise ValueError("Database instance is required in GPTOptions for title saving.")        
        self.__client = genai.Client(
            api_key=options.api_key
        )
        if self.__system_message and self.__file:
            self.__create_cache_content()

    def __create_cache_content(self):
        document = self.__client.files.upload(file=self.__file)
        logging.debug(f"Uploaded document: {document.name}")

         # Define cache configuration (optionally, you could set a short TTL for testing)
        self.__cache_config = {
            "contents": [document],
            "system_instruction": self.__system_message,
            # Uncomment the next line to set a custom TTL (e.g., "60s") for testing expiration.
            # "ttl": "60s",
        }

        # Create an initial cache.
        self.__cached_content = self.__client.caches.create(
            model=self.__model_name,
            config=self.__cache_config,
        )
        logging.info(f"Cache created with name: {self.__cached_content.name}")

    async def complete(
        self, 
        conversation: Conversation, 
        user_message: UserMessage, 
        sent_msg_id: int, 
        system_message: SystemMessage | None
    ) -> AsyncGenerator[AssistantMessage, None]:
        logging.info(f"Completing message for conversation {conversation.id}, message: '{user_message}'")
        logging.debug(f"Current conversation for chat {conversation.id}: {conversation}")
        assistant_message = None
        try:
            async for chunk in self.__stream(([system_message] if system_message else []) + conversation.messages):
                if not assistant_message:
                    assistant_message = AssistantMessage(sent_msg_id, '', user_message.id)
                    conversation.messages.append(assistant_message)

                assistant_message.content += chunk
                yield assistant_message
        except RateLimitException: # Allow RateLimitException from __stream to pass through
            raise
        except Exception as e:
             # Catch other potential errors during the completion setup/yield if needed
             logging.error(f"Error during message completion processing for {conversation.id}: {e}")
             raise # Re-raise other errors
               
        logging.info(f"len(conversation.messages): {len(conversation.messages)}")

        if conversation.title is None and assistant_message and len(conversation.messages) < 3 : # Ensure assistant message exists
            asyncio.create_task(self.__set_title(conversation, self.__db))

        logging.info(f"Completed message for chat {conversation.id}, message: '{assistant_message}'")

    # --- Make set_title an instance method, accept db ---
    async def __set_title(self, conversation: Conversation, db: Database):
        # Check again inside task in case state changed
        if conversation.title is not None:
             return # Already has a title

        logging.info(f"Attempting to generate title for conversation {conversation.id}")
        prompt = 'You are a title generator. You will receive one or multiple messages of a conversation. You will reply with only the title of the conversation without any punctuation mark either at the begining or the end.'
        try:
            # Ensure messages sent to __request include the latest available message content
            # Need at least the user message. If assistant started, include that too.
            messages_for_title = conversation.messages[:2] # Use first 1 or 2 messages
            if not messages_for_title:
                 logging.warning(f"Not enough messages to generate title for conversation {conversation.id}")
                 return

            title = await self.__request(SystemMessage(prompt), messages_for_title)
            title = title.strip()

            if title: # Avoid setting empty titles
                logging.info(f"Generated title for conversation {conversation.id}: '{title}'")
                conversation.title = title # Update in-memory object
                # --- Save to DB ---
                await db.update_conversation(conversation.id, title)
                # ------------------
            else:
                 logging.warning(f"Title generation for conversation {conversation.id} produced empty/invalid result.")
        except RateLimitException:
            logging.warning(f"Rate limit hit during title generation for {conversation.id}. Title not set.")
            # Don't raise here, title is non-critical
        except Exception as title_e:
            logging.error(f"Error generating title for conversation {conversation.id}: {title_e}")
            # Don't raise here, title is non-critical

    def new_conversation(self, conversation_id: int, user_message: UserMessage) -> Conversation:
        conversation = Conversation(conversation_id, None, user_message.timestamp, [user_message])

        if self.__max_message_count and len(conversation.messages) > self.__max_message_count:
            conversation.messages = conversation.messages[self.__max_message_count:]

        return conversation

    async def __request(self, system_message: SystemMessage, messages: list[Message]) -> str:
        try:
            config=types.GenerateContentConfig(
                        system_instruction=
                        [
                            system_message.content
                        ]
                    )
            response: types.GenerateContentResponse = await asyncio.wait_for(
                self.__client.aio.models.generate_content(
                    model=self.__model_name,
                    contents=[message.content for message in messages],
                    config=config
                ),
                timeout=60
            )
            return response.text or ""        
        except google_exceptions.ResourceExhausted as e:
            logging.warning(f"Google API rate limit/quota exceeded in __request: {e}")
            raise RateLimitException(original_exception=e) from e        
        except Exception as e:
            logging.error(f"Error in generate content request: {str(e)}")
            raise

    async def __stream(self, messages: list[Message]) -> AsyncGenerator[str, None]:
        try:
            if self.__system_message and self.__file:
                try:
                    # Check cache content
                    self.__client.caches.get(name=self.__cached_content.name)
                except Exception as e:
                    logging.warning(f"Error in checking cached content: {str(e)}")
                    logging.info("Most likely cache expired. Re-creating cache...")
                    self.__cached_content = self.__client.caches.create(
                        model=self.__model_name,
                        config=self.__cache_config,
                    )
                    logging.info(f"New cache created: {self.__cached_content.name}")

                config = types.GenerateContentConfig(
                    cached_content=self.__cached_content.name,
                    max_output_tokens=1024,
                    #top_k=2,
                    #top_p=0.5,
                    temperature=0.0,
                )
            else:
                config = types.GenerateContentConfig(max_output_tokens=1024)    
            async for chunk in await self.__client.aio.models.generate_content_stream(
                model=self.__model_name,
                contents=[
                        types.Content(
                            role=message.role.value,
                            parts=[types.Part.from_text(text=message.content)]
                        )
                        for message in messages
                    ],
                config=config
            ):
                yield chunk.text
        except google_exceptions.ResourceExhausted as e:
            logging.warning(f"Google API rate limit/quota exceeded in __stream: {e}")
            raise RateLimitException(original_exception=e) from e                
        except Exception as e:
            logging.error(f"Error in streaming content: {str(e)}")
            raise

    async def close(self):
        await self.__client.close()
