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
    # ── legado ──────────────────────────────────────────────────────────────
    # Meta 4: coluna de controle de notificações
    "ALTER TABLE users ADD COLUMN review_notified_at DATETIME",
    # Meta 4: DROP já foi aplicado uma vez; não dropar a cada boot.

    # ── lesson_notes: 6 novas colunas ────────────────────────────────────────
    "ALTER TABLE lesson_notes ADD COLUMN lesson_number INTEGER",
    "ALTER TABLE lesson_notes ADD COLUMN raw_transcript TEXT",
    "ALTER TABLE lesson_notes ADD COLUMN detected_topic TEXT",
    "ALTER TABLE lesson_notes ADD COLUMN student_clarity_score INTEGER",
    "ALTER TABLE lesson_notes ADD COLUMN structured_concepts TEXT",
    "ALTER TABLE lesson_notes ADD COLUMN knowledge_type TEXT",

    # ── review_sessions: 5 novas colunas ─────────────────────────────────────
    # ATENÇÃO: review_sessions foi recriada pela migração "DROP TABLE" acima.
    # Se já existir com a nova estrutura, os ADD COLUMN são no-ops (engolidos).
    "ALTER TABLE review_sessions ADD COLUMN question_id INTEGER",
    "ALTER TABLE review_sessions ADD COLUMN question_text_snapshot TEXT",
    "ALTER TABLE review_sessions ADD COLUMN criteria_evaluation TEXT",
    "ALTER TABLE review_sessions ADD COLUMN identified_gaps TEXT",
    "ALTER TABLE review_sessions ADD COLUMN next_action_taken TEXT",
    "ALTER TABLE review_sessions ADD COLUMN history_json TEXT",

    # ── índices em tabelas existentes ────────────────────────────────────────
    # create_all NÃO cria índices em tabelas que já existem; precisam ser
    # criados explicitamente. IF NOT EXISTS garante idempotência.
    (
        "CREATE INDEX IF NOT EXISTS ix_lesson_notes_subject_lesson "
        "ON lesson_notes(subject_id, lesson_number)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_review_sessions_subject_reviewed "
        "ON review_sessions(subject_id, reviewed_at)"
    ),
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
