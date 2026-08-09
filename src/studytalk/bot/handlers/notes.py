from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
import logging
import tempfile

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from studytalk.bot.keyboards import new_subject_kb, subjects_list_kb
from studytalk.bot.states import LinkNote, Review
from studytalk.bot.users import get_or_create_user
from studytalk.config import settings
from studytalk.db.models import LessonNote, Subject
from studytalk.db.session import AsyncSessionLocal
from studytalk.llm.factory import get_llm_provider
from studytalk.llm.prompts import SUMMARY_PROMPT

router = Router(name="notes")
logger = logging.getLogger(__name__)


@router.message(F.voice, ~StateFilter(Review.waiting_answer))
async def voice_received(message: Message, state: FSMContext) -> None:
    file_id = message.voice.file_id

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, message.from_user.id)
        result = await session.execute(
            select(Subject).where(Subject.user_id == user.id).order_by(Subject.name)
        )
        subjects = list(result.scalars().all())

    if not subjects:
        await state.clear()
        await message.answer(
            "Você ainda não tem matérias. Crie uma primeiro.",
            reply_markup=new_subject_kb(),
        )
        return

    await state.set_state(LinkNote.waiting_subject)
    await state.update_data(pending_file_id=file_id)
    await message.answer(
        "Esse áudio é de qual matéria?",
        reply_markup=subjects_list_kb(subjects, for_linking=True),
    )


@router.callback_query(LinkNote.waiting_subject, F.data.startswith("link:"))
async def link_subject_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()

    try:
        subject_id = int(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.message.answer("Matéria inválida. Envie o áudio de novo.")
        await state.clear()
        return

    data = await state.get_data()
    file_id = data.get("pending_file_id")
    if not file_id:
        await state.clear()
        await callback.message.answer("Não encontrei o áudio pendente. Envie o voice note de novo.")
        return

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        subject = await session.get(Subject, subject_id)
        if subject is None or subject.user_id != user.id:
            await state.clear()
            await callback.message.answer("Matéria não encontrada. Envie o áudio de novo.")
            return

        note = LessonNote(
            subject_id=subject.id,
            user_audio_file_id=file_id,
            improved_summary=None,
        )
        session.add(note)
        await session.commit()
        await session.refresh(note)
        note_id = note.id
        subject_name = subject.name

    await state.clear()
    await callback.message.answer(f"Áudio salvo em {subject_name} ✓")
    await _generate_and_save_summary(
        callback,
        note_id=note_id,
        file_id=file_id,
        subject_name=subject_name,
    )


async def _generate_and_save_summary(
    callback: CallbackQuery,
    *,
    note_id: int,
    file_id: str,
    subject_name: str,
) -> None:
    if not settings.gemini_api_key and settings.llm_provider.lower() == "gemini":
        await callback.message.answer(
            "Áudio salvo, mas a chave da IA não está configurada (`GEMINI_API_KEY`). "
            "Configure o `.env` e envie outro áudio para gerar o resumo."
        )
        return

    await callback.message.answer("Gerando resumo…")

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        await callback.bot.download(file_id, destination=tmp_path)

        provider = get_llm_provider()
        prompt = SUMMARY_PROMPT.format(subject=subject_name)
        summary = await provider.process_audio_to_summary(tmp_path, subject_name, prompt)

        next_review = datetime.now(timezone.utc) + timedelta(days=1)
        async with AsyncSessionLocal() as session:
            note = await session.get(LessonNote, note_id)
            if note is None:
                await callback.message.answer("Resumo gerado, mas não encontrei a nota no banco.")
                return
            note.improved_summary = summary
            note.next_review_at = next_review
            note.review_interval_days = 1
            await session.commit()

        await _send_summary(callback, subject_name=subject_name, summary=summary)

    except Exception as exc:  # noqa: BLE001 — mensagem amigável ao usuário
        logger.exception("Falha ao gerar resumo (note_id=%s): %s", note_id, exc)
        err = str(exc).lower()
        if "429" in err or "quota" in err or "rate" in err or "resource_exhausted" in err:
            msg = "A IA está ocupada (limite de uso). Tente de novo em alguns minutos. O áudio continua salvo."
        elif "404" in err or "not_found" in err or "no longer available" in err:
            msg = "Modelo de IA indisponível. Verifique GEMINI_MODEL no .env. O áudio continua salvo."
        else:
            msg = "Não consegui gerar o resumo agora. O áudio continua salvo — tente enviar de novo mais tarde."
        await callback.message.answer(msg)
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


async def _send_summary(
    callback: CallbackQuery,
    *,
    subject_name: str,
    summary: str,
) -> None:
    header = f"📝 Resumo — {escape(subject_name)}"
    text = f"{header}\n\n{summary}"
    try:
        await callback.message.answer(text, parse_mode="HTML")
    except TelegramBadRequest:
        logger.warning("Resumo com HTML inválido; reenviando em texto puro")
        await callback.message.answer(f"📝 Resumo — {subject_name}\n\n{summary}")


@router.callback_query(F.data.startswith("link:"))
async def link_without_pending(callback: CallbackQuery) -> None:
    """Callback de vínculo sem áudio pendente no FSM."""
    await callback.answer()
    await callback.message.answer("Envie um voice note primeiro para vincular à matéria.")
