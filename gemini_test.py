# Create this file: limcheekin-telegramgpt/gemini_test.py

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, ANY
from datetime import datetime

# Modules to test
from gemini import GPTClient, GPTOptions
from models import Conversation, UserMessage, AssistantMessage, SystemMessage, Role, RateLimitException
from db import Database # Need Database for type hinting and mocking

# Use pytest-asyncio for async tests
pytestmark = pytest.mark.asyncio

# --- Fixtures ---

@pytest.fixture
def mock_db():
    """Fixture for a mocked Database."""
    mock = MagicMock(spec=Database)
    mock.update_conversation = AsyncMock() # Mock the relevant DB method
    return mock

@pytest.fixture
def gpt_options(mock_db):
    """Fixture for GPTOptions with mocked DB."""
    # Provide minimal necessary options for testing title generation
    return GPTOptions(
        api_key="test_api_key",
        db=mock_db
    )

@pytest.fixture
def gpt_client(gpt_options, mocker):
    """Fixture for GPTClient instance with mocked internal client."""
    # Mock the actual genai Client initialization if needed, but for testing
    # __set_title, we primarily need to mock __request.
    with patch('gemini.genai.Client', return_value=MagicMock()):
         client = GPTClient(options=gpt_options)
         # Mock the internal __request method crucial for title generation
         client._GPTClient__request = AsyncMock()
         return client

@pytest.fixture
def sample_conversation_no_title():
    """Fixture for a Conversation object without a title, ready for generation."""
    user_msg = UserMessage(id=100, content="Hello bot!")
    # Add a placeholder assistant message as title gen happens *after* response starts
    assistant_msg = AssistantMessage(id=500, content="Hi!", replied_to_id=100)
    # Make sure started_at is set
    now = datetime.now()
    user_msg.timestamp = now
    assistant_msg.timestamp = now
    return Conversation(
        id=1,
        title=None, # Explicitly None
        started_at=now,
        messages=[user_msg, assistant_msg] # Needs at least user msg for title gen slicing [:2]
    )

@pytest.fixture
def sample_conversation_with_title():
    """Fixture for a Conversation object that already has a title."""
    user_msg = UserMessage(id=101, content="Another query")
    assistant_msg = AssistantMessage(id=501, content="Sure.", replied_to_id=101)
    now = datetime.now()
    user_msg.timestamp = now
    assistant_msg.timestamp = now
    return Conversation(
        id=2,
        title="Existing Title", # Already has a title
        started_at=now,
        messages=[user_msg, assistant_msg]
    )

# --- Test Cases for __set_title ---

async def test_set_title_success(gpt_client, mock_db, sample_conversation_no_title):
    """
    Test successful title generation and saving when title is None.
    """
    conversation = sample_conversation_no_title
    expected_title = "Greeting Bot"
    gpt_client._GPTClient__request.return_value = expected_title # Mock title generation

    # Access and call the private method for testing
    await gpt_client._GPTClient__set_title(conversation, mock_db)

    # Assert __request was called correctly
    gpt_client._GPTClient__request.assert_awaited_once()
    call_args, call_kwargs = gpt_client._GPTClient__request.call_args
    # Check system prompt argument
    system_prompt_arg = call_args[0]
    assert isinstance(system_prompt_arg, SystemMessage)
    assert "You are a title generator" in system_prompt_arg.content
    # Check messages argument (should be the first two messages)
    messages_arg = call_args[1]
    assert messages_arg == conversation.messages[:2]

    # Assert DB update was called
    mock_db.update_conversation.assert_awaited_once_with(conversation.id, expected_title)

    # Assert in-memory conversation title was updated
    assert conversation.title == expected_title

async def test_set_title_already_exists(gpt_client, mock_db, sample_conversation_with_title):
    """
    Test that title generation is skipped if the conversation already has a title.
    """
    conversation = sample_conversation_with_title
    original_title = conversation.title

    # Access and call the private method
    await gpt_client._GPTClient__set_title(conversation, mock_db)

    # Assert __request was NOT called
    gpt_client._GPTClient__request.assert_not_awaited()

    # Assert DB update was NOT called
    mock_db.update_conversation.assert_not_awaited()

    # Assert in-memory conversation title remains unchanged
    assert conversation.title == original_title

async def test_set_title_empty_response_from_request(gpt_client, mock_db, sample_conversation_no_title):
    """
    Test that title is not set if the __request returns an empty or whitespace string.
    """
    conversation = sample_conversation_no_title
    gpt_client._GPTClient__request.return_value = "   " # Mock empty title generation

    # Access and call the private method
    await gpt_client._GPTClient__set_title(conversation, mock_db)

    # Assert __request was called
    gpt_client._GPTClient__request.assert_awaited_once()

    # Assert DB update was NOT called
    mock_db.update_conversation.assert_not_awaited()

    # Assert in-memory conversation title remains None
    assert conversation.title is None

async def test_set_title_request_raises_rate_limit_error(gpt_client, mock_db, sample_conversation_no_title, caplog):
    """
    Test that RateLimitException during title generation is handled gracefully.
    """
    conversation = sample_conversation_no_title
    gpt_client._GPTClient__request.side_effect = RateLimitException("quota exceeded")

    # Access and call the private method - should not raise error
    await gpt_client._GPTClient__set_title(conversation, mock_db)

    # Assert __request was called
    gpt_client._GPTClient__request.assert_awaited_once()

    # Assert DB update was NOT called
    mock_db.update_conversation.assert_not_awaited()

    # Assert in-memory conversation title remains None
    assert conversation.title is None

    # Assert warning log message
    assert "Rate limit hit during title generation" in caplog.text
    assert f"for {conversation.id}" in caplog.text

async def test_set_title_request_raises_general_exception(gpt_client, mock_db, sample_conversation_no_title, caplog):
    """
    Test that a general Exception during title generation is handled gracefully.
    """
    conversation = sample_conversation_no_title
    error_message = "Network connection failed"
    gpt_client._GPTClient__request.side_effect = Exception(error_message)

    # Access and call the private method - should not raise error
    await gpt_client._GPTClient__set_title(conversation, mock_db)

    # Assert __request was called
    gpt_client._GPTClient__request.assert_awaited_once()

    # Assert DB update was NOT called
    mock_db.update_conversation.assert_not_awaited()

    # Assert in-memory conversation title remains None
    assert conversation.title is None

    # Assert error log message
    assert f"Error generating title for conversation {conversation.id}" in caplog.text
    assert error_message in caplog.text

async def test_set_title_db_update_raises_exception(gpt_client, mock_db, sample_conversation_no_title, caplog):
    """
    Test handling of an exception during the database update phase.
    Note: The current broad `except Exception` catches this.
    """
    conversation = sample_conversation_no_title
    expected_title = "Good Title"
    db_error_message = "DB connection lost"

    gpt_client._GPTClient__request.return_value = expected_title
    mock_db.update_conversation.side_effect = Exception(db_error_message)

    # Access and call the private method - should not raise due to broad catch
    await gpt_client._GPTClient__set_title(conversation, mock_db)

    # Assert __request was called
    gpt_client._GPTClient__request.assert_awaited_once()

    # Assert DB update was attempted
    mock_db.update_conversation.assert_awaited_once_with(conversation.id, expected_title)

    # Assert in-memory title IS updated (happens before DB save attempt)
    assert conversation.title == expected_title

    # Assert error log message from the broad exception handler
    assert f"Error generating title for conversation {conversation.id}" in caplog.text
    assert db_error_message in caplog.text