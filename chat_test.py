import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call, ANY
from models import RateLimitException

# Import necessary classes from the project
from chat import (
    ChatManager,
    ChatContext,
    ChatState,
    ConversationMode,
    TELEGRAM_MAX_MESSAGE_LENGTH,
    DEFAULT_EDIT_THROTTLE_INTERVAL_SECONDS
)
from models import (
    Conversation,
    UserMessage,
    AssistantMessage,
    SystemMessage,
    Role
)
# Use the actual GPT client class you are using (Gemini or OpenAI)
# from gpt import GPTClient # If using gpt.py
from gemini import GPTClient # If using gemini.py
from db import Database
from telegram.ext import ExtBot
from telegram import InlineKeyboardMarkup, InlineKeyboardButton

# Use pytest-asyncio for async tests
pytestmark = pytest.mark.asyncio

# --- Fixtures ---

@pytest.fixture
def mock_gpt_client(mocker):
    """Fixture for a mocked GPTClient."""
    mock = MagicMock(spec=GPTClient)
    # *** CHANGE: Use MagicMock for 'complete' ***
    mock.complete = MagicMock()
    return mock

@pytest.fixture
def mock_bot(mocker):
    """Fixture for a mocked ExtBot."""
    mock = MagicMock(spec=ExtBot)
    mock.edit_message_text = AsyncMock()
    mock.send_message = AsyncMock()
    return mock

@pytest.fixture
def mock_db(mocker):
    """Fixture for a mocked Database."""
    mock = MagicMock(spec=Database)
    mock.add_message = AsyncMock()
    mock.update_message = AsyncMock()
    mock.update_conversation = AsyncMock()
    return mock

@pytest.fixture
def mock_chat_state():
    """Fixture for a ChatState."""
    return ChatState()

@pytest.fixture
def mock_chat_data():
    """Fixture for ChatData (dictionary)."""
    return {'conversations': {}, 'modes': {}, 'current_mode_id': None}


@pytest.fixture
def mock_chat_context(mock_chat_state, mock_chat_data, mocker): # Added mocker here
    """Fixture for a ChatContext."""
    mock = MagicMock(spec=ChatContext)
    mock.chat_id = 12345
    mock.chat_state = mock_chat_state
    mock.modes = mock_chat_data['modes']
    mock.current_mode = None
    def set_current_mode_side_effect(mode):
        mock_chat_data['current_mode_id'] = mode.id if mode else None
        mock.current_mode = mode
    mock.set_current_mode = MagicMock(side_effect=set_current_mode_side_effect)
    type(mock).modes = mocker.PropertyMock(return_value=mock_chat_data['modes'])
    return mock


@pytest.fixture
def chat_manager(mock_gpt_client, mock_bot, mock_db, mock_chat_context):
    """Fixture for ChatManager with mocked dependencies."""
    manager = ChatManager(
        gpt=mock_gpt_client,
        speech=None,
        bot=mock_bot,
        context=mock_chat_context,
        conversation_timeout=None,
        db=mock_db
    )
    manager._ChatManager__add_timeout_task = MagicMock()
    manager._ChatManager__edit_throttle_interval = 0.01
    return manager

@pytest.fixture
def sample_conversation():
    """Fixture for a sample Conversation object."""
    user_msg = UserMessage(id=100, content="Hello there")
    # Use a fixed datetime for reproducibility if needed, otherwise datetime.now() is fine
    # from datetime import datetime
    # user_msg.timestamp = datetime(2024, 1, 1, 12, 0, 0)
    return Conversation(id=1, title=None, started_at=user_msg.timestamp, messages=[user_msg])

# --- Helper for Mocking GPT Stream ---

async def mock_gpt_streamer(*chunks):
    """Async generator to simulate gpt.complete yielding chunks."""
    assistant_message_id = 500
    replied_to_id = 100
    accumulated_content = ""
    for chunk_text in chunks:
        accumulated_content += chunk_text
        mock_chunk = MagicMock(spec=AssistantMessage)
        mock_chunk.id = assistant_message_id
        mock_chunk.content = accumulated_content
        mock_chunk.replied_to_id = replied_to_id
        yield mock_chunk
        await asyncio.sleep(0.001)

# --- Test Cases ---

async def test_complete_success_short_response(
    chat_manager, mock_gpt_client, mock_bot, mock_db, sample_conversation, mock_chat_context
):
    """Test successful completion with a short response."""
    chat_id = mock_chat_context.chat_id
    user_message = sample_conversation.messages[-1]
    sent_message_id = 200
    final_content = "Hi! How can I help?"
    assistant_message_id = 500

    # Configure mocks
    # *** CHANGE: Set return_value on the MagicMock 'complete' ***
    mock_gpt_client.complete.return_value = mock_gpt_streamer(final_content)

    # Call the private method
    await chat_manager._ChatManager__complete(sample_conversation, sent_message_id)

    # --- Assertions ---
    # 1. GPT Client called correctly
    # *** CHANGE: Use assert_called_once_with for MagicMock ***
    mock_gpt_client.complete.assert_called_once_with(
        sample_conversation, user_message, sent_message_id, None
    )

    # 2. DB interactions (await assertions are correct for AsyncMocks)
    mock_db.add_message.assert_awaited_once_with(
        assistant_message_id, sample_conversation.id, Role.ASSISTANT.value, ''
    )
    mock_db.update_message.assert_awaited_once_with(
        assistant_message_id, final_content
    )

    # 3. Bot interactions
    final_edit_call = call.edit_message_text(
        chat_id=chat_id,
        message_id=sent_message_id,
        text=final_content
    )
    assert final_edit_call in mock_bot.edit_message_text.await_args_list
    assert mock_bot.edit_message_text.await_count >= 1

    # 4. Conversation state updated
    assert mock_chat_context.chat_state.current_conversation is sample_conversation
    assert len(sample_conversation.messages) == 2
    assistant_msg = sample_conversation.messages[-1]
    assert isinstance(assistant_msg, AssistantMessage)
    assert assistant_msg.id == assistant_message_id
    assert assistant_msg.content == final_content
    assert assistant_msg.replied_to_id == user_message.id

    # 5. Timeout task scheduling attempted
    chat_manager._ChatManager__add_timeout_task.assert_called_once()


async def test_complete_success_streaming_multiple_edits(
    chat_manager, mock_gpt_client, mock_bot, mock_db, sample_conversation
):
    """Test successful completion with multiple streamed chunks and edits."""
    chat_id = chat_manager.context.chat_id
    user_message = sample_conversation.messages[-1]
    sent_message_id = 200
    chunks = ["This ", "is ", "a ", "longer ", "response."]
    final_content = "".join(chunks)
    assistant_message_id = 500

    # *** CHANGE: Set return_value on the MagicMock 'complete' ***
    mock_gpt_client.complete.return_value = mock_gpt_streamer(*chunks)

    await chat_manager._ChatManager__complete(sample_conversation, sent_message_id)

    # *** CHANGE: Use assert_called_once_with for MagicMock 'complete' ***
    mock_gpt_client.complete.assert_called_once_with(
        sample_conversation, user_message, sent_message_id, None
    )

    # DB Assertions
    mock_db.add_message.assert_awaited_once_with(
        assistant_message_id, sample_conversation.id, Role.ASSISTANT.value, ''
    )
    mock_db.update_message.assert_awaited_once_with(
        assistant_message_id, final_content
    )

    # Bot Assertions
    final_call = call.edit_message_text(
        chat_id=chat_id,
        message_id=sent_message_id,
        text=final_content
    )
    assert final_call in mock_bot.edit_message_text.await_args_list
    assert mock_bot.edit_message_text.await_count >= 1

    # Check conversation state
    assert chat_manager.context.chat_state.current_conversation is sample_conversation
    assistant_msg = sample_conversation.messages[-1]
    assert isinstance(assistant_msg, AssistantMessage)
    assert assistant_msg.content == final_content

    chat_manager._ChatManager__add_timeout_task.assert_called_once()

async def test_complete_success_truncation(
    chat_manager, mock_gpt_client, mock_bot, mock_db, sample_conversation
):
    """Test completion where response exceeds Telegram limit and is truncated."""
    chat_id = chat_manager.context.chat_id
    user_message = sample_conversation.messages[-1] # Get user message for call assertion
    sent_message_id = 200
    assistant_message_id = 500
    long_content = "A" * (TELEGRAM_MAX_MESSAGE_LENGTH + 100)
    truncation_suffix = "...\n\n(Type \"continue\" to view more.)"
    max_content_len = TELEGRAM_MAX_MESSAGE_LENGTH - len(truncation_suffix)
    expected_final_text = long_content[:max_content_len] + truncation_suffix

    # *** CHANGE: Set return_value on the MagicMock 'complete' ***
    mock_gpt_client.complete.return_value = mock_gpt_streamer(long_content)

    await chat_manager._ChatManager__complete(sample_conversation, sent_message_id)

    # *** CHANGE: Use assert_called_once_with for MagicMock 'complete' ***
    mock_gpt_client.complete.assert_called_once_with(
        sample_conversation, user_message, sent_message_id, None
    )

    # DB Assertions
    mock_db.add_message.assert_awaited_once()
    mock_db.update_message.assert_awaited_once_with(
        assistant_message_id, expected_final_text
    )

    # Bot Assertions
    final_edit_call = call.edit_message_text(
        chat_id=chat_id,
        message_id=sent_message_id,
        text=expected_final_text
    )
    assert final_edit_call in mock_bot.edit_message_text.await_args_list

    # Check conversation state
    assert chat_manager.context.chat_state.current_conversation is sample_conversation
    assistant_msg = sample_conversation.messages[-1]
    assert isinstance(assistant_msg, AssistantMessage)
    assert assistant_msg.content == long_content

    chat_manager._ChatManager__add_timeout_task.assert_called_once()

async def test_complete_with_system_prompt(
    chat_manager, mock_gpt_client, mock_db, sample_conversation, mock_chat_context
):
    """Test completion when a conversation mode (system prompt) is active."""
    user_message = sample_conversation.messages[-1]
    sent_message_id = 200
    mode_prompt = "You are a helpful pirate."
    mode = ConversationMode(id="pirate-mode", title="Pirate", prompt=mode_prompt)
    mock_chat_context.set_current_mode(mode) # Set mode via the mock's method

    mock_gpt_client.complete.return_value = mock_gpt_streamer("Arr!")

    await chat_manager._ChatManager__complete(sample_conversation, sent_message_id)

    # Assert the call structure using ANY for the system message
    mock_gpt_client.complete.assert_called_once_with(
        sample_conversation,
        user_message,
        sent_message_id,
        ANY  # Use ANY here
    )

    # Now, retrieve the actual arguments and check the system message specifically
    actual_call_args, actual_call_kwargs = mock_gpt_client.complete.call_args
    actual_system_prompt = actual_call_args[3] # system_prompt is the 4th positional arg (index 3)

    assert isinstance(actual_system_prompt, SystemMessage)
    assert actual_system_prompt.content == mode_prompt
    assert actual_system_prompt.role == Role.SYSTEM

    # Add other assertions as needed (DB, bot edits, state)
    # e.g., check DB update
    assistant_message_id = 500 # Assuming this is the ID from mock_gpt_streamer
    final_content = "Arr!"
    mock_db.add_message.assert_awaited_once()
    mock_db.update_message.assert_awaited_once_with(
        assistant_message_id, final_content
    )
    # Check state
    assert len(sample_conversation.messages) == 2
    assert sample_conversation.messages[-1].content == final_content

async def test_complete_gpt_timeout_error(
    chat_manager, mock_gpt_client, mock_bot, mock_db, sample_conversation, caplog
):
    """Test handling of TimeoutError from gpt.complete."""
    chat_id = chat_manager.context.chat_id
    user_message = sample_conversation.messages[-1]
    sent_message_id = 200

    # Configure mocks
    # *** CHANGE: Set side_effect on the MagicMock 'complete' ***
    # Need an async generator that raises the error during iteration
    async def error_streamer():
        await asyncio.sleep(0.01) # Allow event loop to proceed
        raise TimeoutError("GPT took too long")
        yield # Never reached, but makes it a generator function

    mock_gpt_client.complete.return_value = error_streamer()

    await chat_manager._ChatManager__complete(sample_conversation, sent_message_id)

    # Assertions
    # *** CHANGE: Use assert_called_once_with for MagicMock 'complete' ***
    mock_gpt_client.complete.assert_called_once_with(
         sample_conversation, user_message, sent_message_id, None
    )
    mock_db.add_message.assert_not_awaited()
    mock_db.update_message.assert_not_awaited()

    # Check bot edit for timeout message
    retry_markup = InlineKeyboardMarkup([[InlineKeyboardButton('Retry', callback_data='/retry')]])
    mock_bot.edit_message_text.assert_awaited_once_with(
        chat_id=chat_id,
        message_id=sent_message_id,
        text="Generation timed out.",
        reply_markup=retry_markup
    )

    # Check logs
    assert "Timeout generating response" in caplog.text
    assert f"chat {chat_id}" in caplog.text

    # Conversation state
    assert chat_manager.context.chat_state.current_conversation is sample_conversation
    assert len(sample_conversation.messages) == 1

    chat_manager._ChatManager__add_timeout_task.assert_called_once()


async def test_complete_gpt_general_exception(
    chat_manager, mock_gpt_client, mock_bot, mock_db, sample_conversation, caplog
):
    """Test handling of a generic Exception from gpt.complete."""
    chat_id = chat_manager.context.chat_id
    user_message = sample_conversation.messages[-1]
    sent_message_id = 200
    error_message = "Something went wrong"

    # Configure mocks
    # *** CHANGE: Set side_effect on the MagicMock 'complete' ***
    async def error_streamer():
        await asyncio.sleep(0.01)
        raise Exception(error_message)
        yield # Never reached

    mock_gpt_client.complete.return_value = error_streamer()

    await chat_manager._ChatManager__complete(sample_conversation, sent_message_id)

    # Assertions
    # *** CHANGE: Use assert_called_once_with for MagicMock 'complete' ***
    mock_gpt_client.complete.assert_called_once_with(
        sample_conversation, user_message, sent_message_id, None
    )
    mock_db.add_message.assert_not_awaited()
    mock_db.update_message.assert_not_awaited()

    # Check bot edit for generic error message
    retry_markup = InlineKeyboardMarkup([[InlineKeyboardButton('Retry', callback_data='/retry')]])
    mock_bot.edit_message_text.assert_awaited_once_with(
        chat_id=chat_id,
        message_id=sent_message_id,
        text="Sorry, an error occurred.",
        reply_markup=retry_markup
    )

    # Check logs
    assert f"Error generating response for chat {chat_id}" in caplog.text
    assert error_message in caplog.text

    # Conversation state
    assert chat_manager.context.chat_state.current_conversation is sample_conversation
    assert len(sample_conversation.messages) == 1

    chat_manager._ChatManager__add_timeout_task.assert_called_once()

async def test_complete_intermediate_edit_error(
    chat_manager, mock_gpt_client, mock_bot, mock_db, sample_conversation, caplog
):
    """Test handling of an error during an intermediate bot edit."""
    chat_id = chat_manager.context.chat_id
    user_message = sample_conversation.messages[-1]
    sent_message_id = 200
    chunks = ["Chunk1 ", "Chunk2 ", "FinalChunk"]
    final_content = "".join(chunks)
    assistant_message_id = 500
    edit_error_message = "Telegram flood control"

    # *** CHANGE: Set return_value on the MagicMock 'complete' ***
    mock_gpt_client.complete.return_value = mock_gpt_streamer(*chunks)

    # Make the *first* edit call fail, subsequent ones succeed
    # Note: The exact call count depends on throttling and loop speed.
    # We check the final edit call and log message.
    mock_bot.edit_message_text.side_effect = [
        Exception(edit_error_message), # First intermediate edit fails
        AsyncMock(),                 # Allow subsequent edits
        AsyncMock(),
        AsyncMock(), # Add more mocks if more edits are expected
    ]

    await chat_manager._ChatManager__complete(sample_conversation, sent_message_id)

    # Assertions
    # *** CHANGE: Use assert_called_once_with for MagicMock 'complete' ***
    mock_gpt_client.complete.assert_called_once_with(
        sample_conversation, user_message, sent_message_id, None
    )

    # DB should still be updated
    mock_db.add_message.assert_awaited_once()
    mock_db.update_message.assert_awaited_once_with(assistant_message_id, final_content)

    # Bot edits: Check final edit succeeded despite earlier failure
    final_edit_call = call.edit_message_text(
        chat_id=chat_id, message_id=sent_message_id, text=final_content
    )
    # Check the *last* successful call matches the final text
    # Filter out the exception from side_effect list if needed for cleaner check
    successful_calls_args = [
        c.args for c, se in zip(mock_bot.edit_message_text.call_args_list, mock_bot.edit_message_text.side_effect)
        if not isinstance(se, Exception)
    ] if isinstance(mock_bot.edit_message_text.side_effect, list) else mock_bot.edit_message_text.call_args_list

    # A simpler check: ensure the final call is among all calls
    assert final_edit_call in mock_bot.edit_message_text.call_args_list


    # Check logs for the warning
    assert "Non-fatal error editing message during stream" in caplog.text
    assert edit_error_message in caplog.text

    # Conversation state
    assert chat_manager.context.chat_state.current_conversation is sample_conversation
    assistant_msg = sample_conversation.messages[-1]
    assert assistant_msg.content == final_content

    chat_manager._ChatManager__add_timeout_task.assert_called_once()


async def test_complete_final_edit_error(
    chat_manager, mock_gpt_client, mock_bot, mock_db, sample_conversation, caplog
):
    """Test handling of an error during the final bot edit."""
    chat_id = chat_manager.context.chat_id
    user_message = sample_conversation.messages[-1]
    sent_message_id = 200
    final_content = "Final message"
    assistant_message_id = 500
    edit_error_message = "Message not found"

    # *** CHANGE: Set return_value on the MagicMock 'complete' ***
    mock_gpt_client.complete.return_value = mock_gpt_streamer(final_content)

    # Make only the *final* edit call fail
    async def final_edit_failer(*args, **kwargs):
        text = kwargs.get("text", "")
        if "Generating..." not in text: # Heuristic for final edit
            raise Exception(edit_error_message)
        return AsyncMock() # Allow intermediate edits

    mock_bot.edit_message_text.side_effect = final_edit_failer

    await chat_manager._ChatManager__complete(sample_conversation, sent_message_id)

    # Assertions
    # *** CHANGE: Use assert_called_once_with for MagicMock 'complete' ***
    mock_gpt_client.complete.assert_called_once_with(
        sample_conversation, user_message, sent_message_id, None
    )

    # DB should still be updated
    mock_db.add_message.assert_awaited_once()
    mock_db.update_message.assert_awaited_once_with(assistant_message_id, final_content)

    # Check logs for the final edit error
    assert f"Error performing final edit for chat {chat_id}" in caplog.text
    assert edit_error_message in caplog.text

    # Conversation state
    assert chat_manager.context.chat_state.current_conversation is sample_conversation
    assistant_msg = sample_conversation.messages[-1]
    assert assistant_msg.content == final_content

    chat_manager._ChatManager__add_timeout_task.assert_called_once()

async def test_complete_gpt_quota_error( # Renamed for clarity, but old name is fine too
    chat_manager, mock_gpt_client, mock_bot, mock_db, sample_conversation, caplog
):
    """Test handling of RateLimitException raised by the gpt client."""
    chat_id = chat_manager.context.chat_id
    user_message = sample_conversation.messages[-1]
    sent_message_id = 200
    rate_limit_message = "API rate limit hit"

    # Configure mock gpt client's complete method to raise RateLimitException
    # Simulate that the client already caught the specific API error and raised the common one
    async def error_streamer():
        await asyncio.sleep(0.01) # Simulate some delay
        raise RateLimitException(rate_limit_message) # Raise the common exception
        yield # Unreachable

    mock_gpt_client.complete.return_value = error_streamer()

    await chat_manager._ChatManager__complete(sample_conversation, sent_message_id)

    # Assertions
    # 1. GPT Client called
    mock_gpt_client.complete.assert_called_once_with(
         sample_conversation, user_message, sent_message_id, None
    )
    # 2. DB not modified
    mock_db.add_message.assert_not_awaited()
    mock_db.update_message.assert_not_awaited()

    # 3. Check bot edit for the user-facing rate limit message
    mock_bot.edit_message_text.assert_awaited_once_with(
        chat_id=chat_id,
        message_id=sent_message_id,
        text="⏳ The bot is currently busy or has reached a usage limit. Please try again in a few moments."
    )

    # 4. Check logs for the specific warning (should log the RateLimitException message)
    assert "API Rate limit/quota exceeded" in caplog.text # Check generic part of message
    assert f"chat {chat_id}" in caplog.text
    assert rate_limit_message in caplog.text # Check the specific message passed to the exception

    # 5. Conversation state
    assert chat_manager.context.chat_state.current_conversation is sample_conversation
    assert len(sample_conversation.messages) == 1

    # 6. Timeout task scheduling attempted
    chat_manager._ChatManager__add_timeout_task.assert_called_once()

