from datetime import date, datetime, timezone, timedelta
from html import escape
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from sqlalchemy import select

from studytalk.bot.keyboards import days_list_kb, notes_of_day_kb
from studytalk.bot.users import get_or_create_user
from studytalk.db.models import LessonNote, Subject
from studytalk.db.session import AsyncSessionLocal

router = Router(name="notes_browse")
logger = logging.getLogger(__name__)

BRAZIL_TZ = timezone(timedelta(hours=-3))
PAGE_SIZE = 20


def _to_brazil(dt: datetime) -> datetime:
    """Converte datetime do banco (pode ser naive=UTC) para fuso de Brasília."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BRAZIL_TZ)


async def _subject_and_notes(
    telegram_id: int, subject_id: int
) -> tuple[Subject | None, list[LessonNote]]:
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, telegram_id)
        subject = await session.get(Subject, subject_id)
        if subject is None or subject.user_id != user.id:
            return None, []
        result = await session.execute(
            select(LessonNote)
            .where(
                LessonNote.subject_id == subject_id,
                LessonNote.improved_summary.isnot(None),
            )
            .order_by(LessonNote.created_at.desc())
        )
        return subject, list(result.scalars().all())


def _unique_days(notes: list[LessonNote]) -> list[date]:
    seen: set[date] = set()
    days: list[date] = []
    for note in notes:
        d = _to_brazil(note.created_at).date()
        if d not in seen:
            seen.add(d)
            days.append(d)
    return days  # já em ordem DESC (notas vieram DESC do banco)


def _notes_of_day(
    notes: list[LessonNote], target: date
) -> list[tuple[int, ...]]:
    items = [
        (note.id, _to_brazil(note.created_at))
        for note in notes
        if _to_brazil(note.created_at).date() == target
    ]
    return sorted(items, key=lambda x: x[1])  # ASC por hora


# ── Nível 1: lista de dias ────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("subject:view:"))
async def subject_view(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        subject_id = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.message.answer("Matéria inválida.")
        return
    await _render_days(callback, subject_id=subject_id, offset=0, edit=False)


@router.callback_query(F.data.startswith("note:more:"))
async def note_more(callback: CallbackQuery) -> None:
    await callback.answer()
    parts = callback.data.split(":")
    try:
        subject_id = int(parts[2])
        offset = int(parts[3])
    except (IndexError, ValueError):
        await callback.message.answer("Erro de navegação.")
        return
    await _render_days(callback, subject_id=subject_id, offset=offset, edit=True)


async def _render_days(
    callback: CallbackQuery, *, subject_id: int, offset: int, edit: bool
) -> None:
    subject, notes = await _subject_and_notes(callback.from_user.id, subject_id)
    if subject is None:
        await callback.message.answer("Matéria não encontrada.")
        return

    days = _unique_days(notes)
    page = days[offset: offset + PAGE_SIZE]
    has_more = (offset + PAGE_SIZE) < len(days)
    next_offset = offset + PAGE_SIZE

    if not page:
        text = (
            f"<b>{escape(subject.name)}</b>\n\n"
            "Nenhum resumo ainda. Envie um voice note!"
        )
        kb = days_list_kb([], subject_id=subject_id, next_offset=0, has_more=False)
        if edit:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        else:
            await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
        return

    text = f"<b>{escape(subject.name)}</b> — escolha um dia:"
    kb = days_list_kb(page, subject_id=subject_id, next_offset=next_offset, has_more=has_more)
    if edit:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)


# ── Nível 2: notas do dia ─────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("note:day:"))
async def note_day(callback: CallbackQuery) -> None:
    await callback.answer()
    # note:day:<subject_id>:<YYYY-MM-DD>
    parts = callback.data.split(":")
    try:
        subject_id = int(parts[2])
        target_date = date.fromisoformat(parts[3])
    except (IndexError, ValueError):
        await callback.message.answer("Erro de navegação.")
        return

    subject, notes = await _subject_and_notes(callback.from_user.id, subject_id)
    if subject is None:
        await callback.message.answer("Matéria não encontrada.")
        return

    day_items = _notes_of_day(notes, target_date)
    formatted = target_date.strftime("%d/%m/%Y")
    text = f"<b>{escape(subject.name)}</b> — {formatted}:"
    kb = notes_of_day_kb(day_items, subject_id=subject_id, subject_name=subject.name)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


# ── Nível 3: resumo completo ──────────────────────────────────────────────────

@router.callback_query(F.data.startswith("note:read:"))
async def note_read(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        note_id = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.message.answer("Nota inválida.")
        return

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        note = await session.get(LessonNote, note_id)
        if note is None or not note.improved_summary:
            await callback.message.answer("Resumo não encontrado.")
            return
        subject = await session.get(Subject, note.subject_id)
        if subject is None or subject.user_id != user.id:
            await callback.message.answer("Resumo não encontrado.")
            return
        summary = note.improved_summary
        local_dt = _to_brazil(note.created_at)

    header = f"📝 {local_dt.strftime('%d/%m/%Y %Hh%M')}"
    text = f"{header}\n\n{summary}"
    try:
        await callback.message.answer(text, parse_mode="HTML")
    except TelegramBadRequest:
        logger.warning("Resumo com HTML inválido (note_id=%s); reenviando em texto puro", note_id)
        await callback.message.answer(text)
