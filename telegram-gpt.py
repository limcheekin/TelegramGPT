import argparse
import logging
import os
from bot import BotOptions, WebhookOptions, run
from gemini import GPTClient, GPTOptions
from speech import SpeechClient
from db import Database

logging.basicConfig(
  format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
  level=logging.INFO,
)

if __name__ == "__main__":  
  def get_chat_ids_from_env():
    chat_ids = []

    while True:
      chat_id = os.environ.get('TELEGRAM_GPT_CHAT_ID_' + str(len(chat_ids)))
      if chat_id is None:
        break
      chat_ids.append(int(chat_id))

    if 'TELEGRAM_GPT_CHAT_ID' in os.environ:
      chat_ids.append(int(os.environ['TELEGRAM_GPT_CHAT_ID']))

    return chat_ids

  parser = argparse.ArgumentParser()
  parser.add_argument(
    '--openai-api-key',
    type=str,
    default=os.environ.get('TELEGRAM_GPT_OPENAI_API_KEY'),
    required='TELEGRAM_GPT_OPENAI_API_KEY' not in os.environ,
    help="OpenAI API key (https://platform.openai.com/account/api-keys). If --azure-openai-endpoint is specified, this is the Azure OpenAI Service API key.",
  )
  parser.add_argument(
    '--telegram-token',
    type=str,
    default=os.environ.get('TELEGRAM_GPT_TELEGRAM_TOKEN'),
    required='TELEGRAM_GPT_TELEGRAM_TOKEN' not in os.environ,
    help="Telegram bot token. Get it from https://t.me/BotFather.",
  )

  parser.add_argument(
    '--chat-id',
    action='append',
    type=int,
    default=get_chat_ids_from_env(),
    help= "IDs of Allowed chats. Can be specified multiple times. If not specified, the bot will respond to all chats.",
  )
  parser.add_argument(
    '--conversation-timeout',
    type=int,
    default=int(os.environ['TELEGRAM_GPT_CONVERSATION_TIMEOUT']) if 'TELEGRAM_GPT_CONVERSATION_TIMEOUT' in os.environ else None,
    help="Timeout in seconds for a conversation to expire. If not specified, the bot will keep the conversation alive indefinitely.",
  )
  parser.add_argument(
    '--max-message-count',
    type=int,
    default=int(os.environ['TELEGRAM_GPT_MAX_MESSAGE_COUNT']) if 'TELEGRAM_GPT_MAX_MESSAGE_COUNT' in os.environ else None,
    help="Maximum number of messages to keep in the conversation. Earlier messages will be discarded with this option set. If not specified, the bot will keep all messages in the conversation.",
  )

  parser.add_argument(
    '--data-dir',
    type=str,
    default=os.environ.get('TELEGRAM_GPT_DATA_DIR'),
    help="Directory to store data. If not specified, data won't be persisted.",
  )
  parser.add_argument(
    '--webhook-url',
    type=str,
    default=os.environ.get('TELEGRAM_GPT_WEBHOOK_URL'),
    help="URL for telegram webhook requests. If not specified, the bot will use polling mode.",
  )
  parser.add_argument(
    '--webhook-listen-address',
    type=str,
    default=os.environ.get('TELEGRAM_GPT_WEBHOOK_LISTEN_ADDRESS') or '0.0.0.0:80',
    help="Address to listen for telegram webhook requests in the format of <ip>:<port>. Only valid when --webhook-url is set. If not specified, 0.0.0.0:80 would be used.",
  )

  parser.add_argument(
    '--openai-model-name',
    type=str,
    default=os.environ.get('TELEGRAM_GPT_OPENAI_MODEL_NAME') or 'gpt-3.5-turbo',
    help="Chat completion model name (https://platform.openai.com/docs/models/model-endpoint-compatibility). If --azure-openai-endpoint is specified, this is the Azure OpenAI Service model deployment name. Default to be gpt-3.5-turbo.",
  )
  parser.add_argument(
    '--azure-openai-endpoint',
    type=str,
    default=os.environ.get('TELEGRAM_GPT_AZURE_OPENAI_ENDPOINT'),
    help="Azure OpenAI Service endpoint. Set this option to use Azure OpenAI Service instead of OpenAI API."
  )
  parser.add_argument(
    '--start-message-file',
    type=str,
    default=os.environ.get('TELEGRAM_GPT_START_MESSAGE_FILE'),
    help="File specified start message of the bot"
  )  
  parser.add_argument(
    '--system-message-file',
    type=str,
    default=os.environ.get('TELEGRAM_GPT_SYSTEM_MESSAGE_FILE'),
    help="File specified system instructions for cached content"
  )
  parser.add_argument(
    '--context-file',
    type=str,
    default=os.environ.get('TELEGRAM_GPT_CONTEXT_FILE'),
    help="Context file for cached content"
  )
  parser.add_argument(
    '--gemini-implicit-caching',
    type=int,
    default=int(os.environ.get('TELEGRAM_GPT_GEMINI_IMPLICIT_CACHING')) if 'TELEGRAM_GPT_GEMINI_IMPLICIT_CACHING' in os.environ else None,
    help="0: Disable, 1: Enable Gemini 2.5 implicit caching"
  )

  parser.add_argument(
    '--stt-base-url',
    type=str,
    default=os.environ.get('STT_BASE_URL'),
    help="Base URL of the STT API, for example http://127.0.0.1:8000",
  )
  parser.add_argument(
    '--stt-model',
    type=str,
    default=os.environ.get('STT_MODEL'),
    help="Model supported by the STT such as whisper-base, whisper-large-v3-turbo, whisper-large-v3, etc.",
  )
  parser.add_argument(
    '--stt-api-key',
    type=str,
    default=os.environ.get('STT_API_KEY'),
    help="API key of the STT API",
  )
  parser.add_argument(
    '--stt-response-format',
    type=str,
    default=os.environ.get('STT_RESPONSE_FORMAT'),
    help="Response format of the STT API",
  )
  parser.add_argument(
    '--language',
    type=str,
    default=os.environ.get('LANGUAGE'),
    help="Language of the STT and TTS",
  )
  parser.add_argument(
    '--tts-base-url',
    type=str,
    default=os.environ.get('TTS_BASE_URL'),
    help="Base URL of the TTS API, for example http://127.0.0.1:8000/v1",
  )
  parser.add_argument(
    '--tts-api-key',
    type=str,
    default=os.environ.get('TTS_API_KEY'),
    help="API key of the TTS API",
  )
  parser.add_argument(
    '--tts-model',
    type=str,
    default=os.environ.get('TTS_MODEL'),
    help="Model supported by the TTS API",
  )
  parser.add_argument(
    '--tts-voice',
    type=str,
    default=os.environ.get('TTS_VOICE'),
    help="Voice supported by the TTS API",
  )
  parser.add_argument(
    '--tts-backend',
    type=str,
    default=os.environ.get('TTS_BACKEND'),
    help="TTS backend supported by the LocalAI",
  )
  parser.add_argument(
    '--tts-audio-format',
    type=str,
    default=os.environ.get('TTS_AUDIO_FORMAT'),
    help="TTS audio format such as mp3, wav, pcm, etc.",
  )  
  args = parser.parse_args()

  # --- Database Setup ---
  # Use an environment variable for the DSN
  postgres_dsn = os.environ.get('POSTGRES_DSN')
  if not postgres_dsn:
      # Fallback or raise error if persistence is mandatory
      # For example, using SQLite in memory for testing if DSN not set
      # postgres_dsn = "sqlite+aiosqlite:///:memory:"
      # logging.warning("POSTGRES_DSN not set, using in-memory SQLite DB. Data will not persist.")
      # OR
      raise ValueError("POSTGRES_DSN environment variable must be set for database persistence.")

  db = Database(postgres_dsn)
  # ----------------------
  #   
  if args.system_message_file:
    with open(args.system_message_file, "r", encoding="utf-8") as file:
      system_message = file.read()
  else:
    system_message = ""

  if args.start_message_file:
    with open(args.start_message_file, "r", encoding="utf-8") as file:
      start_message = file.read()
  else:
    start_message = "Hello! How can I help you today?"

  # --- Instantiate GPTOptions, passing db ---
  gpt_options = GPTOptions(
      api_key=args.openai_api_key,
      model_name=args.openai_model_name,
      max_message_count=args.max_message_count,
      system_message=system_message,
      context_file=args.context_file,
      implicit_caching=args.gemini_implicit_caching,
      db=db # Pass the initialized db instance
  )
  # -----------------------------------------

  logging.info(f"Initializing GPTClient with options: {gpt_options}")
  gpt = GPTClient(options=gpt_options)

  speech = SpeechClient(
            stt_base_url=args.stt_base_url,
            stt_api_key=args.stt_api_key, 
            stt_model=args.stt_model,
            stt_response_format=args.stt_response_format,  
            tts_base_url=args.tts_base_url,
            tts_api_key=args.tts_api_key,
            tts_model=args.tts_model,
            tts_voice=args.tts_voice,
            tts_backend=args.tts_backend,
            tts_audio_format=args.tts_audio_format,
            language=args.language) if args.stt_base_url is not None and args.tts_base_url is not None else None

  webhook_options = WebhookOptions(args.webhook_url, args.webhook_listen_address) if args.webhook_url is not None else None
  bot_options = BotOptions(args.telegram_token, set(args.chat_id), args.conversation_timeout, 
                           args.data_dir, webhook_options, start_message)
  logging.info(f"Starting bot with options: {bot_options}")

  run(args.telegram_token, gpt, speech, bot_options, db)
