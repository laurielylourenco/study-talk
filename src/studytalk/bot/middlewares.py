from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from studytalk.config import settings


class AllowlistMiddleware(BaseMiddleware):
    """Bloqueia qualquer usuário cujo telegram_id não esteja em ALLOWED_TELEGRAM_IDS."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user

        if user is None:
            return await handler(event, data)

        allowed = settings.allowed_telegram_ids
        if allowed and user.id not in allowed:
            if isinstance(event, Message):
                await event.answer("Este bot é privado.")
            elif isinstance(event, CallbackQuery):
                await event.answer("Este bot é privado.", show_alert=True)
            return None

        return await handler(event, data)
