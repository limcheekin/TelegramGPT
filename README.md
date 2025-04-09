# TelegramGPT (Now with Google Gemini!)

A Telegram bot powered by Google Gemini's API ([Vertex AI / Google AI Studio](https://ai.google.dev/)). This bot leverages PostgreSQL for persistent conversation history and can integrate with self-hosted Speech-to-Text (STT) and Text-to-Speech (TTS) services.

*(Note: This project appears to have migrated from OpenAI's API and Azure Cognitive Services to Google Gemini and self-hosted speech services. The core logic reflects this change.)*

- [Features](#features)
- [Get Started](#get-started)
  - [1. Create a Telegram bot](#1-create-a-telegram-bot)
  - [2. Get a Google Gemini API key](#2-get-a-google-gemini-api-key)
  - [3. Set up PostgreSQL](#3-set-up-postgresql)
  - [4. (Optional) Set up STT/TTS Services](#4-optional-set-up-stttts-services)
  - [5. Deploy](#5-deploy)
- [Usage](#usage)
  - [Conversation](#conversation)
  - [Voice Messages](#voice-messages)
- [Advanced Deployment](#advanced-deployment)
  - [Configuration Environment Variables](#configuration-environment-variables)
  - [Restrict Bot to Specific Chats](#restrict-bot-to-specific-chats)
  - [Conversation Management](#conversation-management)
  - [Data Persistence (PostgreSQL)](#data-persistence-postgresql)
  - [Telegram Bot Webhook](#telegram-bot-webhook)
  - [Support Voice Messages with Custom STT/TTS](#support-voice-messages-with-custom-stttts)
  - [Use a Different Gemini Model](#use-a-different-gemini-model)
  - [Gemini Cached Content (System Prompt & Context File)](#gemini-cached-content-system-prompt--context-file)
  - [Network Proxy](#network-proxy)
  - [Example Docker Compose File](#example-docker-compose-file)
  - [Edit Throttling](#edit-throttling)
- [Options Reference](#options-reference)

## Features

-   Powered by **Google Gemini** models (configurable)
-   **Streaming responses**: See the bot typing in real-time.
-   **Voice message** support using custom/self-hosted STT (e.g., [FastWhisper API](https://github.com/jhj0517/Whisper-API)) and TTS (e.g., Piper TTS via [LocalAI](https://github.com/mudler/LocalAI) or similar OpenAI-compatible endpoint)
-   Persistent **conversation history** stored in PostgreSQL
-   **Resume** previous conversations using `/resume_<id>`
-   Automatic **conversation titling** (generates a title after the first exchange)
-   Restrict bot to specific chats
-   Conversations can automatically time out
-   Supports Gemini's cached content feature for optimized system prompts and context files.

## Get Started

### 1. Create a Telegram bot

Create a Telegram bot using [@BotFather](https://t.me/BotFather) and get the **Telegram Bot Token**.

### 2. Get a Google Gemini API key

Go to [Google AI Studio](https://aistudio.google.com/app/apikey) (or Google Cloud Vertex AI) and create an API key.

### 3. Set up PostgreSQL

This bot requires a PostgreSQL database for storing conversations and messages. Set one up and obtain the **Database Connection String (DSN)**. Example DSN format: `postgresql+asyncpg://user:password@host:port/database`

### 4. (Optional) Set up STT/TTS Services

If you want voice message support:
1.  **Speech-to-Text (STT):** Set up an STT service compatible with the OpenAI Transcription API format. [FastWhisper API](https://github.com/jhj0517/Whisper-API) is one option. Note its **Base URL**, **API Key** (if any), and desired **Model**.
2.  **Text-to-Speech (TTS):** Set up a TTS service compatible with the OpenAI Audio Speech API format. Using [LocalAI](https://github.com/mudler/LocalAI) with a backend like Piper TTS is one way. Note its **Base URL**, **API Key** (if any), **Model**, **Voice**, and **Backend** identifier.

### 5. Deploy

The recommended deployment method is using Docker or Docker Compose.

**Docker:**

```bash
# Clone the repository (if needed)
# git clone https://github.com/limcheekin/TelegramGPT.git
# cd TelegramGPT

# Build the image
docker build -t telegram-gemini-bot .

# Run the container (replace placeholders)
docker run --rm --name telegram-gemini-bot \
  -e TELEGRAM_GPT_TELEGRAM_TOKEN="<YOUR_TELEGRAM_TOKEN>" \
  -e TELEGRAM_GPT_OPENAI_API_KEY="<YOUR_GEMINI_API_KEY>" \
  -e POSTGRES_DSN="<YOUR_POSTGRES_DSN>" \
  # --- Optional Chat ID Restriction ---
  # -e TELEGRAM_GPT_CHAT_ID_0="<ALLOWED_CHAT_ID_1>" \
  # -e TELEGRAM_GPT_CHAT_ID_1="<ALLOWED_CHAT_ID_2>" \
  # --- Optional STT/TTS ---
  # -e FAST_WHISPER_API_BASE_URL="<STT_BASE_URL>" \
  # -e FAST_WHISPER_API_MODEL="<STT_MODEL_NAME>" \
  # -e TTS_BASE_URL="<TTS_BASE_URL>" \
  # -e TTS_MODEL="<TTS_MODEL_NAME>" \
  # -e TTS_VOICE="<TTS_VOICE_NAME>" \
  # -e TTS_BACKEND="<TTS_BACKEND_NAME>" \
  # -e LANGUAGE="en" \
  # --- Other Options ---
  # -e TELEGRAM_GPT_OPENAI_MODEL_NAME="gemini-1.5-pro-latest" \
  # -e TELEGRAM_GPT_CONVERSATION_TIMEOUT="300" \
  # -e TELEGRAM_GPT_SYSTEM_MESSAGE_FILE="/path/in/container/to/system.txt" \
  # -e TELEGRAM_GPT_CONTEXT_FILE="/path/in/container/to/context.pdf" \
  telegram-gemini-bot
```
*(**Note:** The environment variable `TELEGRAM_GPT_OPENAI_API_KEY` is used for the **Google Gemini** API key due to historical naming).*

**Docker Compose:**

Create a `.env` file based on `example.env` and fill in your credentials:

```dotenv
# .env file
# Core
TELEGRAM_GPT_TELEGRAM_TOKEN=<YOUR_TELEGRAM_TOKEN>
TELEGRAM_GPT_OPENAI_API_KEY=<YOUR_GEMINI_API_KEY> # Note: For Gemini Key
POSTGRES_DSN=<YOUR_POSTGRES_DSN>

# LLM Model (Optional)
TELEGRAM_GPT_OPENAI_MODEL_NAME=gemini-1.5-flash-latest # Or another Gemini model

# Chat Restrictions (Optional)
# TELEGRAM_GPT_CHAT_ID_0=<ALLOWED_CHAT_ID_1>
# TELEGRAM_GPT_CHAT_ID_1=<ALLOWED_CHAT_ID_2>

# Conversation Timeout (Optional)
# TELEGRAM_GPT_CONVERSATION_TIMEOUT=600 # seconds

# Voice STT/TTS (Optional)
FAST_WHISPER_API_BASE_URL=<YOUR_STT_BASE_URL> # e.g., http://stt-api:8000
FAST_WHISPER_API_KEY=<YOUR_STT_API_KEY> # Optional
FAST_WHISPER_API_MODEL=base # e.g., base, small, medium
TTS_BASE_URL=<YOUR_TTS_BASE_URL>/v1 # e.g., http://tts-api:8080/v1
TTS_API_KEY=<YOUR_TTS_API_KEY> # Optional
TTS_MODEL=<YOUR_TTS_MODEL> # e.g., tts-model-name
TTS_VOICE=<YOUR_TTS_VOICE> # e.g., en-us-amy
TTS_BACKEND=<YOUR_TTS_BACKEND> # e.g., piper
LANGUAGE=en # Language for STT/TTS

# Gemini Caching (Optional)
# TELEGRAM_GPT_SYSTEM_MESSAGE_FILE=/data/system_prompt.txt # Needs volume mapping
# TELEGRAM_GPT_CONTEXT_FILE=/data/context_document.pdf # Needs volume mapping
```

Use the provided `docker-compose.yaml` (or adapt it):

```yaml
# docker-compose.yaml
services:
  telegram-gpt:
    build: .
    container_name: telegram-gpt
    restart: unless-stopped
    volumes:
      # Mount local files for Gemini Caching if needed
      # - ./my_system_prompt.txt:/data/system_prompt.txt:ro
      # - ./my_context_doc.pdf:/data/context_document.pdf:ro
      # Optional: Mount a directory if needed for other data (though primary data is in DB)
      # - telegram-gpt-data:/data
    env_file:
      - .env # Load variables from .env file
    # If using webhook, expose port and configure network
    # expose:
    #   - 80
    # ports:
    #   - "8080:80" # Map host port 8080 to container port 80

# Optional volume definition if using ./data mount
# volumes:
#   telegram-gpt-data:
```

Then run: `docker compose up -d`

**Default Behaviors:**
- Responds to messages only from chats specified by `TELEGRAM_GPT_CHAT_ID_*` (or all chats if none are specified).
- Uses Google Gemini `gemini-1.5-flash-latest` model.
- Requires a PostgreSQL database connection (`POSTGRES_DSN`).
- Conversations don't automatically time out unless `TELEGRAM_GPT_CONVERSATION_TIMEOUT` is set.
- Bot uses polling unless webhook options are configured.
- Voice messages are disabled unless STT/TTS services are configured.

> **Caution**: If you don't restrict the bot using `TELEGRAM_GPT_CHAT_ID_*`, it will respond to messages from any chat. This can incur costs on the Gemini API as Telegram bots are potentially public.

## Usage

### Conversation

-   Send a message to the bot, and it will respond with a message generated by Gemini.
-   The bot streams responses, so you'll see it "typing".
-   Use the `/retry` command to regenerate the response for the *last user message*.
-   The bot remembers the conversation history within a session.
-   After the first user message and bot response, the bot will automatically generate a title for the conversation.
-   To clear the context and start a fresh conversation, use the `/new` command.
-   To view previous conversations (stored in the database), send the `/history` command. This will list conversations with their titles and IDs.
-   To resume a previous conversation, use the `/resume_<conversation_id>` command (e.g., `/resume_123`) or click the link provided in the `/history` output.

### Voice Messages

Refer to [Support Voice Messages with Custom STT/TTS](#support-voice-messages-with-custom-stttts) for setup instructions.

When enabled:
-   Send a voice message to the bot.
-   It converts the voice message to text using your configured STT service.
-   The text is sent to the Gemini API.
-   The Gemini response text is converted back to a voice message using your configured TTS service.
-   You can also reply to a text message sent by the bot with the `/say` command to have the bot read that specific message aloud using the TTS service.

## Advanced Deployment

### Configuration Environment Variables

The bot is primarily configured through environment variables, as shown in the `Get Started` section and the `Options Reference` table below. You can set these directly when using `docker run` or place them in a `.env` file when using `docker-compose`.

### Restrict Bot to Specific Chats

Use the `TELEGRAM_GPT_CHAT_ID_<n>` environment variables (e.g., `TELEGRAM_GPT_CHAT_ID_0`, `TELEGRAM_GPT_CHAT_ID_1`, etc.) to restrict the bot to specific chats.

If no `TELEGRAM_GPT_CHAT_ID_*` variables are set, the bot will accept messages from any chat (use with caution).

You can find a chat ID by:
1.  Sending a message to your bot *after* it's running (even if restricted). Check the bot's console logs for messages like `Message received for chat XXXXXX but ignored...` or successful processing logs which include the chat ID.
2.  Alternatively, send a message to the bot and then visit `https://api.telegram.org/bot<YOUR_TELEGRAM_TOKEN>/getUpdates` in your browser. Look for the `chat` object and its `id` field in the JSON response.

### Conversation Management

-   **Timeout:** To automatically end a conversation after a period of inactivity (starting a new one on the next message), set the `TELEGRAM_GPT_CONVERSATION_TIMEOUT` environment variable to the desired number of seconds (e.g., `300` for 5 minutes). If not set, conversations persist until `/new` is used.
-   **History Limit (LLM Context):** The `GPTOptions` in `gemini.py` has a `max_message_count` parameter (not directly exposed via env var in `telegram-gpt.py` currently, but could be added). This limits how many *past messages* are sent to the Gemini API in each request to manage token usage. The full history is still stored in the database.

### Data Persistence (PostgreSQL)

Conversation history, messages, and active conversation state per chat are persisted in a PostgreSQL database.
-   **Requirement:** The `POSTGRES_DSN` environment variable **must** be set with a valid PostgreSQL connection string.
-   **Tables Created:** `conversations`, `messages`, `active_conversations`.
-   The old `--data-dir` option seems deprecated for primary data persistence.

### Telegram Bot Webhook

By default, the bot uses polling. To use webhooks (requires a publicly accessible server with HTTPS):
1.  Set the `TELEGRAM_GPT_WEBHOOK_URL` environment variable to your public bot URL (e.g., `https://yourdomain.com/webhookpath`). Telegram only supports ports `443`, `80`, `88`, `8443` for webhooks.
2.  Set the `TELEGRAM_GPT_WEBHOOK_LISTEN_ADDRESS` to the IP address and port the bot should listen on *inside the container* (e.g., `0.0.0.0:80`).
3.  Configure a reverse proxy (like Nginx or Caddy) to handle HTTPS termination and forward requests from the public `TELEGRAM_GPT_WEBHOOK_URL` to the bot's internal `TELEGRAM_GPT_WEBHOOK_LISTEN_ADDRESS`.

Refer to the official [Telegram Bot Webhook Guide](https://core.telegram.org/bots/webhooks) for more details.

### Support Voice Messages with Custom STT/TTS

This bot uses external, potentially self-hosted, services for voice processing, configured via environment variables:
STT_BASE_URL="http://192.168.1.111:8882/v1"
STT_API_KEY="sk-1"
STT_MODEL="large-v3-turbo"
STT_RESPONSE_FORMAT="verbose_json"
LANGUAGE="en"

1.  **Speech-to-Text (STT):**
    *   `STT_BASE_URL`: Base URL of your STT service (e.g., `http://192.168.1.100:8000`). Must be compatible with OpenAI's transcription API format.
    *   `STT_API_KEY`: API key for the STT service (optional, depends on the service).
    *   `STT_MODEL`: The specific STT model to use (e.g., `whisper-base`, `small`, `medium`, `large-v3-turbo`).
    *   `STT_RESPONSE_FORMAT`: Response format expected from the STT service (default to `verbose_json`).
    *   `LANGUAGE`: Language code (e.g., `en`, `es`) used for STT.

2.  **Text-to-Speech (TTS):**
    *   `TTS_BASE_URL`: Base URL of your TTS service (e.g., `http://192.168.1.101:8080/v1`). Must be compatible with OpenAI's speech generation API format.
    *   `TTS_API_KEY`: API key for the TTS service (optional, depends on the service).
    *   `TTS_MODEL`: The specific TTS model/engine name recognized by your service.
    *   `TTS_VOICE`: The specific voice name recognized by your service.
    *   `TTS_BACKEND`: Specific backend identifier if required by your TTS service (e.g., some LocalAI setups).
    *   `TTS_AUDIO_FORMAT`: Audio format expected from the TTS service (default to `mp3`).
    *   `LANGUAGE`: Language code (e.g., `en`, `es`) used for TTS.

If both `STT_BASE_URL` and `TTS_BASE_URL` are provided, voice support is enabled.

### Use a Different Gemini Model

By default, the bot uses `gemini-1.5-flash-latest`. To use a different Gemini chat model (e.g., `gemini-1.5-pro-latest`), set the `TELEGRAM_GPT_OPENAI_MODEL_NAME` environment variable. Refer to [Google AI Gemini models documentation](https://ai.google.dev/models/gemini) for available models.

### Gemini Cached Content (System Prompt & Context File)

Gemini offers a caching feature to reuse processed system instructions and large context files, potentially saving tokens and improving latency.
-   `TELEGRAM_GPT_SYSTEM_MESSAGE_FILE`: Path *inside the container* to a text file containing the system prompt/instructions.
-   `TELEGRAM_GPT_CONTEXT_FILE`: Path *inside the container* to a file (e.g., PDF, TXT) to be used as context.

If you use these, ensure the files are accessible within the container (e.g., via Docker volumes). The bot will upload the file and create a cache on startup. *Note: Caches might expire based on Gemini's policies or TTL if set.*

### Network Proxy

If you need to use an HTTP/HTTPS proxy, configure the standard `http_proxy` and `https_proxy` environment variables for the container.

Docker run:
```bash
docker run -e http_proxy="http://<proxy_ip>:<port>" -e https_proxy="http://<proxy_ip>:<port>" ... telegram-gemini-bot
```

Docker Compose:
```yaml
services:
  telegram-gpt:
    # ... other config ...
    environment:
      # ... other env vars ...
      http_proxy: "http://<proxy_ip>:<port>"
      https_proxy: "http://<proxy_ip>:<port>"
```

### Example Docker Compose File

See the `docker-compose.yaml` file in the repository and the example in the [Get Started](#5-deploy) section. Remember to create a corresponding `.env` file.

### Edit Throttling

To prevent hitting Telegram API rate limits when editing messages for streaming responses, the bot throttles edits. You can adjust the minimum interval (in seconds) between edits using the environment variable `TELEGRAM_GPT_EDIT_THROTTLE_INTERVAL` (default is `0.5`). Setting it lower might provide smoother streaming but increases the risk of rate limiting.

## Options Reference

| Environment Variable                      | Argument Equivalent                | Description                                                                                                 | Default                      | Required             |
| :---------------------------------------- | :--------------------------------- | :---------------------------------------------------------------------------------------------------------- | :--------------------------- | :------------------- |
| `TELEGRAM_GPT_TELEGRAM_TOKEN`             | `--telegram-token`                 | Telegram bot token from @BotFather.                                                                         | -                            | **Yes**              |
| `TELEGRAM_GPT_OPENAI_API_KEY`             | `--openai-api-key`                 | **Google Gemini API key** from Google AI Studio. (Name is historical).                                      | -                            | **Yes**              |
| `POSTGRES_DSN`                            | *(None)*                           | PostgreSQL Database Connection String (e.g., `postgresql+asyncpg://user:pass@host:port/db`).                    | -                            | **Yes**              |
| `TELEGRAM_GPT_OPENAI_MODEL_NAME`          | `--openai-model-name`              | Gemini chat model name.                                                                                     | `gemini-1.5-flash-latest`    | No                   |
| `TELEGRAM_GPT_CHAT_ID_0`, `_1`, ...       | `--chat-id` (multiple)             | Allowed Telegram chat IDs. If none set, allows all chats.                                                   | Allow all                    | No                   |
| `TELEGRAM_GPT_CONVERSATION_TIMEOUT`       | `--conversation-timeout`           | Timeout in seconds for conversations to expire.                                                             | `None` (No timeout)          | No                   |
| `TELEGRAM_GPT_MAX_MESSAGE_COUNT`          | `--max-message-count`              | *Currently not used by `telegram-gpt.py` for BotOptions, but available in `GPTOptions`.*                     | `None`                       | No                   |
| `TELEGRAM_GPT_DATA_DIR`                   | `--data-dir`                       | Directory for data (primarily used by Dockerfile, persistence now mainly via PostgreSQL).                   | `/data` (in container)       | No                   |
| `TELEGRAM_GPT_WEBHOOK_URL`                | `--webhook-url`                    | Public URL for Telegram webhook requests (enables webhook mode).                                            | `None` (Polling mode)        | No                   |
| `TELEGRAM_GPT_WEBHOOK_LISTEN_ADDRESS`     | `--webhook-listen-address`         | Internal IP:Port for the bot to listen on for webhook requests.                                             | `0.0.0.0:80`                 | No (if webhook used) |
| `TELEGRAM_GPT_SYSTEM_MESSAGE_FILE`        | `--system-message-file`            | Path to file containing system instructions for Gemini cached content.                                      | `None`                       | No                   |
| `TELEGRAM_GPT_CONTEXT_FILE`               | `--context-file`                   | Path to context file for Gemini cached content.                                                             | `None`                       | No                   |
| `TTS_BASE_URL`                            | `--tts-base-url`                   | Base URL for the Text-to-Speech (TTS) API service. Enables voice output if `FAST_WHISPER_API_BASE_URL` is set. | `None`                       | No                   |
| `TTS_API_KEY`                             | `--tts-api-key`                    | API Key for the TTS service (if required).                                                                  | `None`                       | No                   |
| `TTS_MODEL`                               | `--tts-model`                      | Model name for the TTS service.                                                                             | `None`                       | No (if TTS used)     |
| `TTS_VOICE`                               | `--tts-voice`                      | Voice name for the TTS service.                                                                             | `None`                       | No (if TTS used)     |
| `TTS_BACKEND`                             | `--tts-backend`                    | Backend identifier for the TTS service (if required).                                                       | `None`                       | No                   |
| `LANGUAGE`                                | `--language`                       | Language code (e.g., `en`, `es`) for STT and TTS services.                                                  | `None`                       | No (if STT/TTS used) |
| `TELEGRAM_GPT_EDIT_THROTTLE_INTERVAL`     | *(None)*                           | Minimum seconds between message edits during streaming response.                                            | `0.5`                        | No                   |
