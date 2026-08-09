from collections.abc import AsyncGenerator
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from studytalk.config import settings
from studytalk.db.models import Base

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

_MIGRATIONS = [
    # Meta 4: coluna de controle de notificações
    "ALTER TABLE users ADD COLUMN review_notified_at DATETIME",
    # Meta 4: recriar review_sessions com subject_id (tabela vazia, seguro dropar)
    "DROP TABLE IF EXISTS review_sessions",
]


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for sql in _MIGRATIONS:
            try:
                await conn.execute(text(sql))
                logger.info("Migração aplicada: %s", sql[:60])
            except Exception:
                pass  # coluna/tabela já existe ou migration não aplicável
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
