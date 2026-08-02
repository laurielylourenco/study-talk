import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from studytalk.bot.handlers import notes, start, subjects
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

    dp.include_router(start.router)
    dp.include_router(subjects.router)
    dp.include_router(notes.router)

    logger.info("Polling started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
