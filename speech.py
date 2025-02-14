import aiohttp
from io import BytesIO
from openai import OpenAI

class SpeechClient:
  def __init__(self,  
               fastwhisperapi_base_url: str, 
               fastwhisperapi_model: str,  
               tts_base_url: str,
               tts_api_key: str, 
               tts_model: str,
               tts_voice: str,
               tts_backend: str,  
               fastwhisperapi_key: str = 'dummy_api_key',
               language: str = 'en',
               checked_fastwhisperapi: bool = False):
    self.__session = aiohttp.ClientSession(trust_env=True)
    self.__fastwhisperapi_base_url = fastwhisperapi_base_url
    self.__fastwhisperapi_model = fastwhisperapi_model
    self.__fastwhisperapi_key = fastwhisperapi_key
    self.__checked_fastwhisperapi = checked_fastwhisperapi
    self.__language = language
    self.__tts_base_url = tts_base_url
    self.__tts_api_key = tts_api_key
    self.__tts_model = tts_model
    self.__tts_voice = tts_voice
    self.__tts_backend = tts_backend

  async def check_fastwhisperapi(self):
      """Check if the FastWhisper API is running."""
      if not self.__checked_fastwhisperapi:
          info_endpoint = f"{self.__fastwhisperapi_base_url}/info"
          try:
              response = await self.__session.get(info_endpoint)
              if response.status_code != 200:
                  raise Exception("FastWhisperAPI is not running")
          except Exception:
              raise Exception("FastWhisperAPI is not running")
          self.__checked_fastwhisperapi = True

  async def speech_to_text(self, audio: bytearray, message_id: str) -> str:
    # await self.check_fastwhisperapi()
    endpoint = f"{self.__fastwhisperapi_base_url}/v1/audio/transcriptions"
    client = OpenAI(api_key=self.__fastwhisperapi_key, base_url=f'{self.__fastwhisperapi_base_url}/v1')
    # Convert the bytearray to a BytesIO file-like object
    audio_file = BytesIO(audio)
    audio_file.name = f'{message_id}.wav'
    response = client.audio.transcriptions.create(
        model=self.__fastwhisperapi_model,
        file=audio_file,
        language=self.__language,
    )
    return response.text


  async def text_to_speech(self, text: str) -> bytes:
    client = OpenAI(api_key=self.__tts_api_key, base_url=self.__tts_base_url)
    response = client.audio.speech.create(
                model=self.__tts_model,
                voice=self.__tts_voice,
                input=text,
                extra_body={"backend": self.__tts_backend, "language": self.__language},
            )
    return response.read()
  
  """
  The audio streaming is working but doesn't improve the usability and response time in Telegram
  async def text_to_speech(self, text: str) -> bytes:
      audio_buffer = BytesIO()

      client = AsyncOpenAI(api_key=self.__tts_api_key, base_url=self.__tts_base_url)
      
      # Using an async context manager to create the streaming response.
      async with client.audio.speech.with_streaming_response.create(
          model=self.__tts_model,
          voice=self.__tts_voice,
          input=text,
          extra_body={"backend": self.__tts_backend, "language": self.__language},
      ) as response:
          # Asynchronously iterate over chunks of audio data.
          async for chunk in response.iter_bytes():
              audio_buffer.write(chunk)
    
      # Return the collected bytes.
      return audio_buffer.getvalue()
  """

  async def close(self):
    await self.__session.close()
