import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from studytalk.bot.handlers import notes, notes_browse, start, subjects
from studytalk.bot.middlewares import AllowlistMiddleware
from studytalk.config import settings
from studytalk.db.session import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    await init_db()
    logger.info("Database ready")

    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.middleware(AllowlistMiddleware())
    dp.callback_query.middleware(AllowlistMiddleware())

    dp.include_router(start.router)
    dp.include_router(subjects.router)
    dp.include_router(notes_browse.router)
    dp.include_router(notes.router)

    if settings.allowed_telegram_ids:
        logger.info("Allowlist ativa: %s", settings.allowed_telegram_ids)
    else:
        logger.warning("Allowlist vazia — bot aceita qualquer usuário")

    logger.info("Ambiente: %s [%s]", settings.app_env, settings.env_badge)

    logger.info("Polling started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
