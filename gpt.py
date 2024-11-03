import asyncio
from dataclasses import dataclass, field
import logging
from typing import AsyncGenerator, cast
from openai import AsyncOpenAI, AsyncAzureOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from models import AssistantMessage, Conversation, Message, SystemMessage, UserMessage

@dataclass
class GPTOptions:
    api_key: str = field(repr=False)
    model_name: str = 'gpt-3.5-turbo'
    azure_endpoint: str | None = None
    max_message_count: int | None = None

class GPTClient:
    def __init__(self, *, options: GPTOptions):
        self.__model_name = options.model_name
        self.__max_message_count = options.max_message_count
        self.__is_azure = options.azure_endpoint is not None

        if self.__is_azure:
            self.__client = AsyncAzureOpenAI(
                api_key=options.api_key,
                azure_endpoint=options.azure_endpoint,
                api_version="2023-05-15"
            )
        else:
            self.__client = AsyncOpenAI(
                api_key=options.api_key
            )

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

        async for chunk in self.__stream(([system_message] if system_message else []) + conversation.messages):
            if not assistant_message:
                assistant_message = AssistantMessage(sent_msg_id, '', user_message.id)
                conversation.messages.append(assistant_message)

            assistant_message.content += chunk
            yield assistant_message

        if conversation.title is None and len(conversation.messages) < 3:
            async def set_title(conversation: Conversation):
                prompt = 'You are a title generator. You will receive one or multiple messages of a conversation. You will reply with only the title of the conversation without any punctuation mark either at the begining or the end.'
                messages = [SystemMessage(prompt)] + conversation.messages

                title = await self.__request(messages)
                conversation.title = title

                logging.info(f"Set title for conversation {conversation}: '{title}'")

            asyncio.create_task(set_title(conversation))

        logging.info(f"Completed message for chat {conversation.id}, message: '{assistant_message}'")

    def new_conversation(self, conversation_id: int, user_message: UserMessage) -> Conversation:
        conversation = Conversation(conversation_id, None, user_message.timestamp, [user_message])

        if self.__max_message_count and len(conversation.messages) > self.__max_message_count:
            conversation.messages = conversation.messages[self.__max_message_count:]

        return conversation

    async def __request(self, messages: list[Message]) -> str:
        try:
            response: ChatCompletion = await asyncio.wait_for(
                self.__client.chat.completions.create(
                    model=self.__model_name,
                    messages=[{'role': message.role, 'content': message.content} for message in messages],
                ),
                timeout=60
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logging.error(f"Error in chat completion request: {str(e)}")
            raise

    async def __stream(self, messages: list[Message]) -> AsyncGenerator[str, None]:
        try:
            stream = await self.__client.chat.completions.create(
                model=self.__model_name,
                messages=[{'role': message.role, 'content': message.content} for message in messages],
                stream=True
            )
            async for chunk in stream:
                chunk = cast(ChatCompletionChunk, chunk)
                if content := chunk.choices[0].delta.content:
                    yield content
        except Exception as e:
            logging.error(f"Error in streaming chat completion: {str(e)}")
            raise

    async def close(self):
        await self.__client.close()
