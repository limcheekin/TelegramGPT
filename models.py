from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from db import DBConversation, DBMessage

class Role(str, Enum):
  SYSTEM = 'system'
  ASSISTANT = 'assistant'
  USER = 'user'

@dataclass
class Message:
  id: int
  role: Role
  content: str
  timestamp: datetime

  @classmethod
  def from_db_message(cls, db_message: DBMessage) -> 'Message':
      """
      Convert a DBMessage to a Message domain model
      
      Args:
          db_message (DBMessage): Database message model
      
      Returns:
          Message: Domain model representation
      """
      return cls(
          id=db_message.id,
          role=Role(db_message.role),
          content=db_message.content,
          timestamp=db_message.timestamp
      )
  
  def to_db_model(self, conversation_id: int) -> DBMessage:
      """
      Convert the current Message to a DBMessage
      
      Args:
          conversation_id (int): ID of the parent conversation
      
      Returns:
          DBMessage: Database representation of the message
      """
      return DBMessage(
          id=self.id,
          conversation_id=conversation_id,
          role=self.role.value,
          content=self.content,
          timestamp=self.timestamp
      )  

class SystemMessage(Message):
  def __init__(self, content: str, timestamp: datetime|None = None):
    super().__init__(-1, Role.SYSTEM, content, timestamp or datetime.now())

class AssistantMessage(Message):
  replied_to_id: int

  def __init__(self, id: int, content: str, replied_to_id: int, timestamp: datetime|None = None):
    super().__init__(id, Role.ASSISTANT, content, timestamp or datetime.now())
    self.id = id
    self.replied_to_id = replied_to_id

class UserMessage(Message):
  answer_id: int|None

  def __init__(self, id: int, content: str, timestamp: datetime|None = None):
    super().__init__(id, Role.USER, content, timestamp or datetime.now())
    self.id = id
    self.answer_id = None

@dataclass
class Conversation:
  id: int
  title: str|None
  started_at: datetime
  messages: list[Message]

  @property
  def last_message(self):
    if len(self.messages) == 0:
      return None
    return self.messages[-1]

  @classmethod
  def from_db_model(cls, db_conversation: DBConversation) -> 'Conversation':
      """
      Convert a DBConversation to a Conversation domain model
      
      Args:
          db_conversation (DBConversation): Database conversation model
      
      Returns:
          Conversation: Domain model representation
      """
      messages = [
          Message.from_db_message(db_message) for db_message in db_conversation.messages
      ]
      
      return cls(
          id=db_conversation.id,
          title=db_conversation.title,
          started_at=db_conversation.started_at,
          messages=messages
      )
  
  def to_db_model(self) -> DBConversation:
      """
      Convert the current Conversation to a DBConversation
      
      Returns:
          DBConversation: Database representation of the conversation
      """
      db_conversation = DBConversation(
          id=self.id,
          chat_id=None,
          title=self.title,
          started_at=self.started_at,
          updated_at=datetime.now()
      )
      
      db_conversation.messages = [
          message.to_db_model(conversation_id=db_conversation.id) 
          for message in self.messages
      ]
      
      return db_conversation