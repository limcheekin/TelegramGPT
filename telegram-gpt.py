import argparse
import logging
import os
from bot import BotOptions, WebhookOptions, run
from gpt import GPTClient, GPTOptions
from speech import SpeechClient

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
    '--fast-whisper-api-base-url',
    type=str,
    default=os.environ.get('FAST_WHISPER_API_BASE_URL'),
    help="Base URL of the FastWhisperAPI, for example http://127.0.0.1:8000",
  )
  parser.add_argument(
    '--fast-whisper-api-model',
    type=str,
    default=os.environ.get('FAST_WHISPER_API_MODEL'),
    help="Model supported by the FastWhisperAPI such as tiny.en, tiny, base.en, base, small.en, small, medium.en, medium, large-v1, large-v2, large-v3, large-v3-turbo, large, distil-large-v2, distil-medium.en, distil-small.en, distil-large-v3",
  )
  parser.add_argument(
    '--fast-whisper-api-key',
    type=str,
    default=os.environ.get('FAST_WHISPER_API_KEY'),
    help="API key of the FastWhisperAPI",
  )
  parser.add_argument(
    '--language',
    type=str,
    default=os.environ.get('LANGUAGE'),
    help="Language of the FastWhisperAPI and TTS",
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
  args = parser.parse_args()

  gpt_options = GPTOptions(args.openai_api_key, args.openai_model_name, args.azure_openai_endpoint, args.max_message_count)
  logging.info(f"Initializing GPTClient with options: {gpt_options}")
  gpt = GPTClient(options=gpt_options)

  speech = SpeechClient(
            fastwhisperapi_base_url=args.fast_whisper_api_base_url,
            fastwhisperapi_key=args.fast_whisper_api_key,
            fastwhisperapi_model=args.fast_whisper_api_model,
            checked_fastwhisperapi=True,
            tts_base_url=args.tts_base_url,
            tts_api_key=args.tts_api_key,
            tts_model=args.tts_model,
            tts_voice=args.tts_voice,
            tts_backend=args.tts_backend,
            language=args.language) if args.fast_whisper_api_base_url is not None and args.tts_base_url is not None else None

  webhook_options = WebhookOptions(args.webhook_url, args.webhook_listen_address) if args.webhook_url is not None else None
  bot_options = BotOptions(args.telegram_token, set(args.chat_id), args.conversation_timeout, args.data_dir, webhook_options)
  logging.info(f"Starting bot with options: {bot_options}")

  run(args.telegram_token, gpt, speech, bot_options)
