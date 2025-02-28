import logging
import uuid
from datetime import datetime
from typing import Optional, List, Literal
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base, relationship, joinedload
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, 
    func, select, update, event
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.exc import SQLAlchemyError

logging.basicConfig(level=logging.INFO)
Base = declarative_base()

# region Models
class DBConversation(Base):
    __tablename__ = 'conversations'
    id = Column(Integer, primary_key=True)
    title = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        index=True
    )
    messages = relationship("DBMessage", back_populates="conversation", cascade="all, delete-orphan")

class DBMessage(Base):
    __tablename__ = 'messages'
    id = Column(Integer, primary_key=True)
    conversation_id = Column(
        Integer, 
        ForeignKey('conversations.id', ondelete="CASCADE"), 
        nullable=False, 
        index=True  # Index for frequent joins
    )
    role = Column(String(20), nullable=False)  # Enforce length limit
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    conversation = relationship("DBConversation", back_populates="messages")

class DBConversationMode(Base):
    __tablename__ = 'conversation_modes'
    id = Column(
        UUID(as_uuid=True), 
        primary_key=True, 
        default=uuid.uuid4  # Server-side UUID generation
    )
    title = Column(Text, nullable=False)
    prompt = Column(Text, nullable=False)
# endregion

class Database:
    def __init__(self, dsn: str):
        self.engine = create_async_engine(dsn, echo=False, future=True)
        self.SessionLocal = sessionmaker(
            self.engine, 
            expire_on_commit=False, 
            class_=AsyncSession
        )
        
        # Add event listener for SQLite to enable foreign keys, 
        # for testing purposes
        if "sqlite" in dsn:
            @event.listens_for(self.engine.sync_engine, "connect")
            def sqlite_set_foreign_keys(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()        

    async def init_db(self) -> None:
        """Initialize database tables and indexes."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logging.info("Database initialized.")

    async def create_conversation(self, title: Optional[str] = None) -> DBConversation:
        """Create a new conversation with server-generated timestamps."""
        async with self.SessionLocal() as session:
            try:
                async with session.begin():
                    # For SQLite tests, set the timestamp explicitly
                    now = datetime.now()
                    conv = DBConversation(
                        title=title,
                        started_at=now,
                        updated_at=now
                    )
                    session.add(conv)
                # Refresh to load server-generated values
                await session.refresh(conv)
                return conv
            except SQLAlchemyError as e:
                logging.error("Database error creating conversation: %s", e)
                raise

    async def add_message(
        self, 
        conversation_id: int, 
        role: Literal['user', 'assistant', 'system'], 
        content: str,
        session: Optional[AsyncSession] = None
    ) -> DBMessage:
        """
        Add a message with role validation and efficient updated_at update.
        Optionally use an external session for transaction management.
        """
        close_session = session is None
        session = session or self.SessionLocal()
        
        try:
            # Validate role
            if role not in {'user', 'assistant', 'system'}:
                raise ValueError(f"Invalid role: {role}")

            if close_session:
                await session.begin()
                
            msg = DBMessage(
                conversation_id=conversation_id,
                role=role,
                content=content,
                timestamp=datetime.now()
            )
            session.add(msg)
            
            # Update conversation's updated_at directly with explicit timestamp
            await session.execute(
                update(DBConversation)
                .where(DBConversation.id == conversation_id)
                .values(updated_at=datetime.now())
            )
            
            if close_session:
                await session.commit()
                await session.refresh(msg)
            
            return msg
        except Exception as e:
            if close_session and session.in_transaction():
                await session.rollback()
            logging.error("Database error adding message: %s", e)
            raise
        finally:
            if close_session:
                await session.close()

    async def update_message(
        self, 
        message_id: int, 
        new_content: str,
        session: Optional[AsyncSession] = None
    ) -> Optional[DBMessage]:
        """Update message content and conversation's updated_at."""
        close_session = session is None
        session = session or self.SessionLocal()
        
        try:
            if close_session:
                await session.begin()
                
            msg = await session.get(DBMessage, message_id)
            if not msg:
                return None
                
            msg.content = new_content
            
            # Update conversation timestamp with explicit timestamp
            await session.execute(
                update(DBConversation)
                .where(DBConversation.id == msg.conversation_id)
                .values(updated_at=datetime.now())
            )
            
            if close_session:
                await session.commit()
                await session.refresh(msg)
                
            return msg
        except SQLAlchemyError as e:
            if close_session and session.in_transaction():
                await session.rollback()
            logging.error("Database error updating message: %s", e)
            raise
        finally:
            if close_session:
                await session.close()

    async def get_conversation(self, conversation_id: int) -> Optional[DBConversation]:
        async with self.SessionLocal() as session:
            try:
                stmt = (
                    select(DBConversation)
                    .options(joinedload(DBConversation.messages))
                    .where(DBConversation.id == conversation_id)
                )
                result = await session.execute(stmt)
                return result.scalar()
            except SQLAlchemyError as e:
                logging.error("Database error getting conversation: %s", e)
                raise

    async def list_conversations(
        self, 
        skip: int = 0, 
        limit: Optional[int] = None,
        order_by: Literal['started_at', 'updated_at'] = 'started_at',
        order_dir: Literal['asc', 'desc'] = 'desc',
        ids: Optional[List[int]] = None
    ) -> List[DBConversation]:
        """
        List conversations with pagination, sorting, and optional ID filtering.
        
        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return
            order_by: Field to sort by ('started_at' or 'updated_at')
            order_dir: Sort direction ('asc' or 'desc')
            ids: Optional list of conversation IDs to filter by
            
        Returns:
            List of DBConversation objects
        """
        skip = max(0, skip)
        if limit is not None:
            limit = max(0, limit)
            
        async with self.SessionLocal() as session:
            try:
                # Determine sort column and direction
                sort_column = getattr(DBConversation, order_by)
                if order_dir == 'desc':
                    sort_column = sort_column.desc()
                
                query = select(DBConversation).order_by(sort_column)
                
                # Filter by IDs if provided
                if ids:
                    query = query.where(DBConversation.id.in_(ids))
                    
                query = query.offset(skip).limit(limit)
                result = await session.execute(query)
                return result.scalars().all()
            except SQLAlchemyError as e:
                logging.error("Database error listing conversations: %s", e)
                raise

    # region Conversation Modes
    async def create_conversation_mode(self, title: str, prompt: str) -> DBConversationMode:
        """Create a new conversation mode with UUID."""
        async with self.SessionLocal() as session:
            try:
                async with session.begin():
                    # Ensure proper UUID handling
                    mode = DBConversationMode(
                        id=uuid.uuid4(),  # Explicitly generate UUID
                        title=title, 
                        prompt=prompt
                    )
                    session.add(mode)
                    await session.commit()
                await session.refresh(mode)
                return mode
            except SQLAlchemyError as e:
                logging.error("Database error creating conversation mode: %s", e)
                raise
    # endregion