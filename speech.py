from openai import AsyncOpenAI
from io import BytesIO
import logging

class SpeechClient:
  def __init__(self,  
               stt_base_url: str,
               stt_api_key: str, 
               stt_model: str,
               stt_response_format: str,  
               tts_base_url: str,
               tts_api_key: str, 
               tts_model: str,
               tts_voice: str,
               tts_backend: str,
               tts_audio_format: str,
               language: str = 'en'):
    logging.info(f"language {language}")
    self.__stt_model = stt_model
    self.__stt_response_format = stt_response_format
    self.__language = language
    self.__tts_model = tts_model
    self.__tts_voice = tts_voice
    self.__tts_backend = tts_backend
    self.__tts_audio_format = tts_audio_format
    # Initialize async clients
    self.__tts_client = AsyncOpenAI(api_key=tts_api_key, base_url=tts_base_url)
    self.__stt_client = AsyncOpenAI(api_key=stt_api_key, base_url=stt_base_url)

  async def speech_to_text(self, audio: bytearray, message_id: str) -> str:
      """Asynchronous version of speech-to-text conversion"""
      audio_file = BytesIO(audio)
      audio_file.name = f'{message_id}.wav'
      response = await self.__stt_client.audio.transcriptions.create(
          model=self.__stt_model,
          file=audio_file,
          language=self.__language,
          response_format=self.__stt_response_format,
      )
      return response.text.lstrip()

  async def text_to_speech(self, text: str) -> bytes:
    response = await self.__tts_client.audio.speech.create(
                model=self.__tts_model,
                voice=self.__tts_voice,
                input=text,
                response_format=self.__tts_audio_format,
                extra_body={"backend": self.__tts_backend, "language": self.__language},
            )
    return response.read()