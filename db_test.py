import pytest
import asyncio
import sqlalchemy as sa
from sqlalchemy import func, update, event, select
from sqlalchemy.exc import IntegrityError, DBAPIError
from db import Base, Database, DBConversation, DBMessage, DBConversationMode
from pytest_asyncio import fixture as pytest_asyncio_fixture

TEST_DSN = "sqlite+aiosqlite:///:memory:"

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

# Existing tests here...

@pytest.mark.asyncio
async def test_max_content_length(db):
    """Test maximum content length handling (database-specific limit)"""
    # PostgreSQL TEXT type has no inherent length limit, but practical limits apply
    huge_content = "x" * 10_000_000  # 10MB
    conv = await db.create_conversation()
    msg = await db.add_message(conv.id, "user", huge_content)
    assert len(msg.content) == 10_000_000

@pytest.mark.asyncio
async def test_nonexistent_conversation_message(db):
    """Test adding message to non-existent conversation"""
    with pytest.raises(IntegrityError) as exc_info:
        await db.add_message(99999, "user", "test")
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
async def test_rollback_on_error(db):
    """Test transaction rollback on invalid operation"""
    conv = await db.create_conversation()
    initial_updated = conv.updated_at
    
    try:
        # Valid message followed by invalid operation
        await db.add_message(conv.id, "user", "valid")
        await db.add_message(conv.id, "invalid_role", "test")
    except ValueError:
        pass
    
    # Verify partial transaction was rolled back
    updated_conv = await db.get_conversation(conv.id)
    assert len(updated_conv.messages) == 0
    assert updated_conv.updated_at == initial_updated

@pytest.mark.asyncio
async def test_concurrent_updates(db):
    """Test race condition handling for updated_at (optimistic locking)"""
    conv = await db.create_conversation()
    initial_updated = conv.updated_at

    # Simulate concurrent updates
    async def update_conversation():
        async with db.SessionLocal() as session:
            await session.execute(
                update(DBConversation)
                .where(DBConversation.id == conv.id)
                .values(updated_at=func.now())
            )
            await session.commit()

    # Run multiple updates concurrently
    await asyncio.gather(*[update_conversation() for _ in range(5)])
    
    final_conv = await db.get_conversation(conv.id)
    assert final_conv.updated_at > initial_updated

@pytest.mark.asyncio
async def test_message_with_null_content(db):
    """Test database constraints for required fields"""
    conv = await db.create_conversation()
    with pytest.raises(IntegrityError):
        async with db.SessionLocal() as session:
            msg = DBMessage(
                conversation_id=conv.id,
                role="user",
                content=None  # Violates NOT NULL constraint
            )
            session.add(msg)
            await session.commit()

@pytest.mark.asyncio
async def test_ordering_of_conversations(db):
    """Test various sorting combinations"""
    # Create test conversations with known timestamps
    conv1 = await db.create_conversation()
    conv2 = await db.create_conversation()
    conv3 = await db.create_conversation()

    # Test ascending order by started_at
    convs = await db.list_conversations(order_by='started_at', order_dir='asc')
    assert [c.id for c in convs] == [conv1.id, conv2.id, conv3.id]

    # Test descending order by updated_at
    await db.add_message(conv3.id, "user", "Update")
    convs = await db.list_conversations(order_by='updated_at', order_dir='desc')
    assert convs[0].id == conv3.id

@pytest.mark.asyncio
async def test_eager_loading_queries(db):
    """Verify eager loading doesn't make extra queries"""
    conv = await db.create_conversation()
    await db.add_message(conv.id, "user", "Test")

    # Count the number of queries executed
    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import AsyncConnection
    
    query_count = 0
    
    def before_execute(conn, clauseelement, multiparams, params):
        nonlocal query_count
        query_count += 1
    
    async with db.engine.connect() as conn:
        event.listens_for(conn.sync_connection, 'before_execute')(before_execute)
        
        conv = await db.get_conversation(conv.id)
        assert len(conv.messages) == 1
    
    assert query_count == 1  # Single query with JOIN

@pytest.mark.asyncio
async def test_cascading_deletes(db):
    """Test conversation deletion cascades to messages"""
    conv = await db.create_conversation()
    await db.add_message(conv.id, "user", "Test")
    
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
async def test_invalid_uuid_handling(db):
    """Test invalid UUID format handling"""
    with pytest.raises(DBAPIError):
        async with db.SessionLocal() as session:
            # Try to insert invalid UUID manually
            invalid_uuid = "not-a-real-uuid"
            stmt = sa.insert(DBConversationMode).values(
                id=invalid_uuid,
                title="Invalid",
                prompt="Test"
            )
            await session.execute(stmt)
            await session.commit()

@pytest.mark.asyncio
async def test_duplicate_conversation_modes(db):
    """Test creation of conversation modes with duplicate titles"""
    mode1 = await db.create_conversation_mode("Duplicate", "Prompt 1")
    mode2 = await db.create_conversation_mode("Duplicate", "Prompt 2")
    assert mode1.id != mode2.id
    assert mode1.title == mode2.title