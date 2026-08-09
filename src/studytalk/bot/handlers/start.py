from aiogram import F, Router
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from studytalk.bot.keyboards import main_menu_kb
from studytalk.bot.users import get_or_create_user
from studytalk.config import settings
from studytalk.db.session import AsyncSessionLocal

router = Router(name="start")


def welcome_text() -> str:
    badge = settings.env_badge
    return (
        f"Olá! Eu sou o EstudoBot. [{badge}]\n\n"
        "Cadastre suas matérias e envie voice notes explicando o que entendeu. "
        "Eu guardo tudo organizado por matéria.\n\n"
        "Escolha uma opção:"
    )


async def send_main_menu(message: Message) -> None:
    async with AsyncSessionLocal() as session:
        await get_or_create_user(session, message.from_user.id)
    await message.answer(welcome_text(), reply_markup=main_menu_kb())


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await send_main_menu(message)


@router.callback_query(F.data == "menu:send_audio")
async def menu_send_audio(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(
        "Envie um voice note agora — eu pergunto a qual matéria vincular."
    )


@router.message(StateFilter(None), F.text & ~F.text.startswith("/"))
async def text_outside_flow(message: Message, state: FSMContext) -> None:
    """Texto fora de FSM ativo → menu principal (A9)."""
    await state.clear()
    await send_main_menu(message)
