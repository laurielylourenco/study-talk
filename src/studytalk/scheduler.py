import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from sqlalchemy import select

from studytalk.db.models import LessonNote, Subject, User
from studytalk.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

NOTIFY_COOLDOWN_HOURS = 6
CHECK_INTERVAL_SECONDS = 3600  # 1 hora


async def _users_with_due_reviews() -> list[tuple[int, int, str]]:
    """Retorna lista de (telegram_id, user_id, subject_names_str) para usuários com revisões vencidas."""
    now = datetime.now(timezone.utc)
    cooldown_threshold = now - timedelta(hours=NOTIFY_COOLDOWN_HOURS)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User)
            .join(Subject, Subject.user_id == User.id)
            .join(LessonNote, LessonNote.subject_id == Subject.id)
            .where(
                LessonNote.improved_summary.isnot(None),
                LessonNote.next_review_at <= now,
            )
            .distinct()
        )
        users = list(result.scalars().all())

    due_users: list[tuple[int, int, str]] = []
    for user in users:
        if (
            user.review_notified_at is not None
            and user.review_notified_at >= cooldown_threshold
        ):
            continue

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Subject.name)
                .join(LessonNote, LessonNote.subject_id == Subject.id)
                .where(
                    Subject.user_id == user.id,
                    LessonNote.improved_summary.isnot(None),
                    LessonNote.next_review_at <= datetime.now(timezone.utc),
                )
                .distinct()
            )
            subject_names = [row[0] for row in result.all()]

        if subject_names:
            due_users.append((user.telegram_id, user.id, ", ".join(subject_names)))

    return due_users


async def _mark_notified(user_id: int) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            user.review_notified_at = datetime.now(timezone.utc)
            await session.commit()


async def run_scheduler(bot: Bot) -> None:
    logger.info("Scheduler de revisão iniciado (intervalo: %ds)", CHECK_INTERVAL_SECONDS)
    while True:
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
        try:
            due_users = await _users_with_due_reviews()
            for telegram_id, user_id, subject_names in due_users:
                count = len(subject_names.split(", "))
                text = (
                    f"⏰ Hora de revisar!\n\n"
                    f"Você tem <b>{count}</b> matéria(s) pendente(s) hoje:\n"
                    f"<i>{subject_names}</i>\n\n"
                    "Toque em Revisar para começar."
                )
                try:
                    from studytalk.bot.keyboards import main_menu_kb
                    await bot.send_message(telegram_id, text, parse_mode="HTML", reply_markup=main_menu_kb())
                    await _mark_notified(user_id)
                    logger.info("Notificação enviada para telegram_id=%s", telegram_id)
                except Exception as exc:
                    logger.warning("Falha ao notificar telegram_id=%s: %s", telegram_id, exc)
        except Exception as exc:
            logger.exception("Erro no scheduler de revisão: %s", exc)
