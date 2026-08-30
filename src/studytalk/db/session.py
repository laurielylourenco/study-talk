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


_LEGACY_RS_TABLE = "review_sessions_legacy"

# Colunas copiadas da tabela legada para a reconstruída, na ordem do INSERT.
_RS_COPY_COLUMNS = (
    "id",
    "subject_id",
    "question_id",
    "question_text_snapshot",
    "user_audio_file_id",
    "feedback",
    "score",
    "reviewed_at",
    "criteria_evaluation",
    "identified_gaps",
    "next_action_taken",
    "history_json",
)


async def _review_sessions_columns(conn) -> set[str]:
    result = await conn.execute(text("PRAGMA table_info(review_sessions)"))
    return {row[1] for row in result.fetchall()}


async def _stash_legacy_review_sessions(conn) -> bool:
    """Aparta a review_sessions da Meta 4 para o create_all recriá-la.

    Aquela tabela tinha `question TEXT NOT NULL`, coluna que o modelo atual não
    preenche mais: todo INSERT falhava com IntegrityError e a revisão nunca
    começava. ADD COLUMN não remove coluna, então só a reconstrução resolve.
    """
    if "question" not in await _review_sessions_columns(conn):
        return False

    # O índice é global no SQLite e sobreviveria ao RENAME, colidindo com o
    # que o create_all vai criar na tabela nova.
    await conn.execute(text("DROP INDEX IF EXISTS ix_review_sessions_subject_reviewed"))
    await conn.execute(text(f"DROP TABLE IF EXISTS {_LEGACY_RS_TABLE}"))
    await conn.execute(text(f"ALTER TABLE review_sessions RENAME TO {_LEGACY_RS_TABLE}"))
    logger.info("review_sessions legada apartada para reconstrução")
    return True


async def _restore_review_sessions(conn) -> None:
    legacy_cols = {
        row[1]
        for row in (
            await conn.execute(text(f"PRAGMA table_info({_LEGACY_RS_TABLE})"))
        ).fetchall()
    }

    def source(column: str) -> str:
        if column == "question_text_snapshot":
            available = [c for c in ("question_text_snapshot", "question") if c in legacy_cols]
            return f"COALESCE({', '.join(available)})" if available else "NULL"
        if column == "history_json":
            return "COALESCE(history_json, '[]')" if "history_json" in legacy_cols else "'[]'"
        return column if column in legacy_cols else "NULL"

    await conn.execute(
        text(
            f"INSERT INTO review_sessions ({', '.join(_RS_COPY_COLUMNS)}) "
            f"SELECT {', '.join(source(c) for c in _RS_COPY_COLUMNS)} "
            f"FROM {_LEGACY_RS_TABLE}"
        )
    )
    migrated = (
        await conn.execute(text("SELECT COUNT(*) FROM review_sessions"))
    ).scalar()
    await conn.execute(text(f"DROP TABLE {_LEGACY_RS_TABLE}"))
    logger.info("review_sessions reconstruída (%s sessões preservadas)", migrated)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for sql in _MIGRATIONS:
            try:
                await conn.execute(text(sql))
                logger.info("Migração aplicada: %s", sql[:60])
            except Exception:
                pass  # coluna/tabela já existe ou migration não aplicável
        had_legacy_rs = await _stash_legacy_review_sessions(conn)
        await conn.run_sync(Base.metadata.create_all)
        if had_legacy_rs:
            await _restore_review_sessions(conn)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
