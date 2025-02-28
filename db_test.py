import pytest
import asyncio
from datetime import datetime, timedelta
from sqlalchemy import update, event, select
from sqlalchemy.exc import IntegrityError
from db import Base, Database, DBConversation, DBMessage, DBConversationMode
from pytest_asyncio import fixture as pytest_asyncio_fixture
import logging
logging.basicConfig(level=logging.DEBUG)

TEST_DSN = "sqlite+aiosqlite:///:memory:"
CHAT_ID = 1234567

@pytest_asyncio_fixture(scope="module")
async def db():
    test_db = Database(TEST_DSN)
    await test_db.init_db()
    yield test_db
    # Cleanup
    async with test_db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest_asyncio_fixture(autouse=True)
async def cleanup(db):
    """Cleanup all data between tests using transaction rollback"""
    async with db.engine.connect() as conn:
        tx = await conn.begin()
        yield
        await tx.rollback()

@pytest.mark.asyncio
async def test_rollback_on_error(request, db):
    """Test transaction rollback on invalid operation"""
    conv = await db.create_conversation(CHAT_ID)
    initial_updated = conv.updated_at
    
    # Use a single transaction for multiple operations
    async with db.SessionLocal() as session:
        try:
            async with session.begin():
                # Valid message followed by invalid operation
                request.config.MESSAGE_ID += 1
                await db.add_message(request.config.MESSAGE_ID, conv.id, "user", "valid", session=session)
                request.config.MESSAGE_ID += 1
                await db.add_message(request.config.MESSAGE_ID, conv.id, "invalid_role", "test", session=session)
        except ValueError:
            pass  # Exception is expected
    
    # Verify partial transaction was rolled back
    updated_conv = await db.get_conversation(conv.id)
    assert len(updated_conv.messages) == 0

@pytest.mark.asyncio
async def test_concurrent_updates(db):
    """Test race condition handling for updated_at (explicit timestamps)"""
    conv = await db.create_conversation(CHAT_ID)
    initial_updated = conv.updated_at
    
    # Simulate concurrent updates with explicit timestamps
    async def update_conversation(increment_seconds):
        async with db.SessionLocal() as session:
            # Use explicit timestamp instead of func.now()
            new_time = datetime.now() + timedelta(seconds=increment_seconds)
            await session.execute(
                update(DBConversation)
                .where(DBConversation.id == conv.id)
                .values(updated_at=new_time)
            )
            await session.commit()
    
    # Run multiple updates with different timestamps
    await asyncio.gather(*[update_conversation(i) for i in range(1, 6)])
    
    # Force refresh to get the latest data
    async with db.SessionLocal() as session:
        refreshed_conv = await session.get(DBConversation, conv.id)
        await session.refresh(refreshed_conv)
        assert refreshed_conv.updated_at > initial_updated

@pytest.mark.asyncio
async def test_ordering_of_conversations(db):
    """Test various sorting combinations"""
    # Create test conversations with known timestamps
    conv1 = await db.create_conversation(CHAT_ID)
    conv2 = await db.create_conversation(CHAT_ID)
    conv3 = await db.create_conversation(CHAT_ID)
    
    test_ids = [conv1.id, conv2.id, conv3.id]
    
    # Test ascending order by started_at with specific IDs
    convs = await db.list_conversations(order_by='started_at', order_dir='asc', ids=test_ids)
    assert [c.id for c in convs] == [conv1.id, conv2.id, conv3.id]
    
    # Test descending order by updated_at
    # Update with explicit timestamp to ensure ordering
    async with db.SessionLocal() as session:
        await session.execute(
            update(DBConversation)
            .where(DBConversation.id == conv3.id)
            .values(updated_at=datetime.now() + timedelta(seconds=10))
        )
        await session.commit()
    
    convs = await db.list_conversations(order_by='updated_at', order_dir='desc', ids=test_ids)
    assert convs[0].id == conv3.id

@pytest.mark.asyncio
async def test_eager_loading_queries(request, db):
    """Verify eager loading doesn't make extra queries"""
    conv = await db.create_conversation(CHAT_ID)
    request.config.MESSAGE_ID += 1
    await db.add_message(request.config.MESSAGE_ID, conv.id, "user", "Test")

    # Count the number of queries executed
    query_count = 0

    def before_execute(conn, clauseelement, multiparams, params, execution_options):
        nonlocal query_count
        query_count += 1
        logging.debug(f'*query_count {query_count}')

    # Attach event listener globally
    event.listen(db.engine.sync_engine, 'before_execute', before_execute)

    try:
        conv = await db.get_conversation(conv.id)
        assert len(conv.messages) == 1
        assert query_count == 1  # Single query with JOIN
    finally:
        # Clean up event listener
        event.remove(db.engine.sync_engine, 'before_execute', before_execute)

@pytest.mark.asyncio
async def test_invalid_uuid_handling(db):
    """Test invalid UUID format handling"""
    with pytest.raises(Exception) as exc_info:
        async with db.SessionLocal() as session:
            async with session.begin():
                # SQLAlchemy UUID type validation
                invalid_mode = DBConversationMode(
                    id="not-a-real-uuid",  # This should fail during validation
                    title="Invalid",
                    prompt="Test"
                )
                session.add(invalid_mode)
                await session.flush()  # This will trigger the validation error
    
    # Verify the error is UUID related
    assert "UUID" in str(exc_info.value) or "uuid" in str(exc_info.value) or "hex" in str(exc_info.value)

@pytest.mark.asyncio
async def test_max_content_length(request, db):
    """Test maximum content length handling (database-specific limit)"""
    # PostgreSQL TEXT type has no inherent length limit, but practical limits apply
    huge_content = "x" * 10_000_000  # 10MB
    conv = await db.create_conversation(CHAT_ID)
    request.config.MESSAGE_ID += 1
    msg = await db.add_message(request.config.MESSAGE_ID, conv.id, "user", huge_content)
    assert len(msg.content) == 10_000_000

@pytest.mark.asyncio
async def test_nonexistent_conversation_message(request, db):
    """Test adding message to non-existent conversation"""
    with pytest.raises(IntegrityError) as exc_info:
        request.config.MESSAGE_ID += 1
        await db.add_message(request.config.MESSAGE_ID, 99999, "user", "test")
    assert "foreign key constraint" in str(exc_info.value).lower()

@pytest.mark.asyncio
async def test_update_nonexistent_message(db):
    """Test updating a message that doesn't exist"""
    result = await db.update_message(99999, "new content")
    assert result is None

@pytest.mark.asyncio
async def test_invalid_pagination(db):
    """Test pagination with negative values"""
    # Should clamp negative values to 0
    convs = await db.list_conversations(skip=-10, limit=-5)
    assert len(convs) == 0

@pytest.mark.asyncio
async def test_nonexistent_conversation_retrieval(db):
    """Test retrieving non-existent conversation"""
    result = await db.get_conversation(99999)
    assert result is None

@pytest.mark.asyncio
async def test_message_with_null_content(request, db):
    """Test database constraints for required fields"""
    conv = await db.create_conversation(CHAT_ID)
    with pytest.raises(IntegrityError):
        async with db.SessionLocal() as session:
            msg = DBMessage(
                id=request.config.MESSAGE_ID,
                conversation_id=conv.id,
                role="user",
                content=None  # Violates NOT NULL constraint
            )
            session.add(msg)
            await session.commit()

@pytest.mark.asyncio
async def test_cascading_deletes(request, db):
    """Test conversation deletion cascades to messages"""
    conv = await db.create_conversation(CHAT_ID)
    request.config.MESSAGE_ID += 1
    await db.add_message(request.config.MESSAGE_ID, conv.id, "user", "Test")
    
    # Manual delete to test cascade (not exposed in Database class)
    async with db.SessionLocal() as session:
        conv = await session.get(DBConversation, conv.id)
        await session.delete(conv)
        await session.commit()
    
    # Verify messages were deleted
    async with db.SessionLocal() as session:
        result = await session.execute(
            select(DBMessage).where(DBMessage.conversation_id == conv.id)
        )
        assert result.scalars().all() == []

@pytest.mark.asyncio
async def test_duplicate_conversation_modes(db):
    """Test creation of conversation modes with duplicate titles"""
    mode1 = await db.create_conversation_mode("Duplicate", "Prompt 1")
    mode2 = await db.create_conversation_mode("Duplicate", "Prompt 2")
    assert mode1.id != mode2.id
    assert mode1.title == mode2.title