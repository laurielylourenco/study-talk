from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from studytalk.bot.keyboards import new_subject_kb, subjects_list_kb
from studytalk.bot.states import CreateSubject
from studytalk.bot.users import get_or_create_user
from studytalk.db.models import Subject
from studytalk.db.session import AsyncSessionLocal

router = Router(name="subjects")


async def _list_subjects_for_user(telegram_id: int) -> tuple[list[Subject], int]:
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, telegram_id)
        result = await session.execute(
            select(Subject).where(Subject.user_id == user.id).order_by(Subject.name)
        )
        subjects = list(result.scalars().all())
        return subjects, user.id


async def show_subjects_menu(message: Message, telegram_id: int) -> None:
    subjects, _ = await _list_subjects_for_user(telegram_id)
    if not subjects:
        await message.answer(
            "Você ainda não tem matérias.",
            reply_markup=new_subject_kb(),
        )
        return

    await message.answer(
        "Suas matérias:",
        reply_markup=subjects_list_kb(subjects, for_linking=False),
    )


@router.message(Command("materias"))
async def cmd_materias(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_subjects_menu(message, message.from_user.id)


@router.callback_query(F.data == "menu:subjects")
async def menu_subjects(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await show_subjects_menu(callback.message, callback.from_user.id)


@router.callback_query(F.data == "subject:new")
async def subject_new(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(CreateSubject.waiting_name)
    await callback.message.answer("Qual o nome da matéria?")



@router.message(CreateSubject.waiting_name, F.text)
async def subject_name_received(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Envie um nome válido para a matéria.")
        return
    if len(name) > 120:
        await message.answer("Nome muito longo (máx. 120 caracteres). Tente de novo.")
        return

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, message.from_user.id)
        subject = Subject(user_id=user.id, name=name)
        session.add(subject)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            await state.clear()
            await message.answer("Você já tem uma matéria com esse nome.")
            return

    await state.clear()
    await message.answer(f"Matéria '{name}' criada! ✓")
