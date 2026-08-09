from datetime import datetime, timedelta, timezone
from html import escape
import logging
import tempfile
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from studytalk.bot.keyboards import main_menu_kb, review_feedback_kb
from studytalk.bot.states import Review
from studytalk.db.models import LessonNote, ReviewSession, Subject
from studytalk.db.session import AsyncSessionLocal
from studytalk.llm.factory import get_llm_provider

router = Router(name="review")
logger = logging.getLogger(__name__)

BRAZIL_TZ = timezone(timedelta(hours=-3))


async def _due_subject(user_id: int) -> tuple[int, str, datetime] | None:
    """Retorna (subject_id, subject_name, oldest_due) da matéria com nota mais antiga vencida, ou None."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(
                Subject.id,
                Subject.name,
                LessonNote.next_review_at,
            )
            .join(LessonNote, LessonNote.subject_id == Subject.id)
            .where(
                Subject.user_id == user_id,
                LessonNote.improved_summary.isnot(None),
                LessonNote.next_review_at <= datetime.now(timezone.utc),
            )
            .order_by(LessonNote.next_review_at.asc())
            .limit(1)
        )
        row = result.first()
        if row is None:
            return None
        return row.id, row.name, row.next_review_at


async def _next_review_info(user_id: int) -> str:
    """Texto com a próxima revisão agendada, ou mensagem genérica."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Subject.name, LessonNote.next_review_at)
            .join(LessonNote, LessonNote.subject_id == Subject.id)
            .where(
                Subject.user_id == user_id,
                LessonNote.improved_summary.isnot(None),
                LessonNote.next_review_at.isnot(None),
            )
            .order_by(LessonNote.next_review_at.asc())
            .limit(1)
        )
        row = result.first()
    if row is None:
        return "Nenhuma revisão agendada ainda. Envie um áudio para começar!"
    local_dt = row.next_review_at.astimezone(BRAZIL_TZ)
    return (
        f"Nenhuma revisão pendente agora.\n"
        f"Próxima: <b>{escape(row.name)}</b> em {local_dt.strftime('%d/%m às %Hh%M')}."
    )


async def _due_notes_for_subject(subject_id: int) -> list[LessonNote]:
    """Todas as notas vencidas de uma matéria com resumo."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(LessonNote)
            .where(
                LessonNote.subject_id == subject_id,
                LessonNote.improved_summary.isnot(None),
                LessonNote.next_review_at <= datetime.now(timezone.utc),
            )
            .order_by(LessonNote.next_review_at.asc())
        )
        return list(result.scalars().all())


async def _count_pending_subjects(user_id: int) -> int:
    """Quantas matérias ainda têm notas vencidas (além da que acabou de ser revisada)."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Subject.id)
            .join(LessonNote, LessonNote.subject_id == Subject.id)
            .where(
                Subject.user_id == user_id,
                LessonNote.improved_summary.isnot(None),
                LessonNote.next_review_at <= datetime.now(timezone.utc),
            )
            .distinct()
        )
        return len(result.all())


@router.callback_query(F.data == "menu:review")
async def start_review(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()

    from studytalk.bot.users import get_or_create_user
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        user_id = user.id

    due = await _due_subject(user_id)
    if due is None:
        info = await _next_review_info(user_id)
        await callback.message.answer(info, parse_mode="HTML", reply_markup=main_menu_kb())
        return

    subject_id, subject_name, _ = due
    notes = await _due_notes_for_subject(subject_id)
    if not notes:
        await callback.message.answer("Nenhuma revisão pendente.", reply_markup=main_menu_kb())
        return

    combined = "\n\n---\n\n".join(
        f"[Nota {i + 1}]\n{n.improved_summary}" for i, n in enumerate(notes)
    )

    await callback.message.answer("Gerando pergunta de revisão…")
    try:
        provider = get_llm_provider()
        question = await provider.generate_review_question(combined)
    except Exception as exc:
        logger.exception("Falha ao gerar pergunta: %s", exc)
        await callback.message.answer(
            "Não consegui gerar a pergunta agora. Tente de novo em alguns minutos.",
            reply_markup=main_menu_kb(),
        )
        return

    async with AsyncSessionLocal() as session:
        rs = ReviewSession(subject_id=subject_id, question=question)
        session.add(rs)
        await session.commit()
        await session.refresh(rs)
        session_id = rs.id

    note_ids = [n.id for n in notes]
    await state.set_state(Review.waiting_answer)
    await state.update_data(
        subject_id=subject_id,
        subject_name=subject_name,
        question=question,
        session_id=session_id,
        due_note_ids=note_ids,
        user_id=user_id,
    )

    header = f"📖 <b>{escape(subject_name)}</b> — {len(notes)} nota(s) vencida(s)\n\n"
    await callback.message.answer(
        f"{header}🎯 <b>Pergunta:</b> {escape(question)}\n\n"
        "Responda com um voice note explicando com suas palavras:",
        parse_mode="HTML",
    )


@router.message(Review.waiting_answer, F.voice)
async def receive_review_answer(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    subject_name: str = data["subject_name"]
    question: str = data["question"]
    session_id: int = data["session_id"]
    due_note_ids: list[int] = data["due_note_ids"]
    user_id: int = data["user_id"]

    await state.clear()
    await message.answer("Avaliando sua resposta…")

    file_id = message.voice.file_id
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        await message.bot.download(file_id, destination=tmp_path)

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(LessonNote).where(LessonNote.id.in_(due_note_ids))
            )
            notes = list(result.scalars().all())

        combined = "\n\n---\n\n".join(
            f"[Nota {i + 1}]\n{n.improved_summary}" for i, n in enumerate(notes)
        )

        provider = get_llm_provider()
        evaluation = await provider.evaluate_audio_answer(tmp_path, combined, question)
        feedback: str = evaluation["feedback"]
        score: int = evaluation["score"]

    except Exception as exc:
        logger.exception("Falha ao avaliar resposta (session_id=%s): %s", session_id, exc)
        await message.answer(
            "Não consegui avaliar sua resposta agora. Tente de novo.",
            reply_markup=main_menu_kb(),
        )
        return
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        rs = await session.get(ReviewSession, session_id)
        if rs:
            rs.user_audio_file_id = file_id
            rs.feedback = feedback
            rs.score = score
            rs.reviewed_at = now

        result = await session.execute(
            select(LessonNote).where(LessonNote.id.in_(due_note_ids))
        )
        notes = list(result.scalars().all())
        for note in notes:
            current_interval = note.review_interval_days or 1
            new_interval = current_interval * 2 if score == 1 else 1
            note.review_interval_days = new_interval
            note.next_review_at = now + timedelta(days=new_interval)

        await session.commit()

    result_icon = "✅" if score == 1 else "❌"
    if score == 1:
        interval_msg = f"Próxima revisão de <b>{escape(subject_name)}</b>: cada nota avançou o intervalo."
    else:
        interval_msg = f"Não se preocupe! <b>{escape(subject_name)}</b> volta amanhã para nova tentativa."

    pending = await _count_pending_subjects(user_id)
    pending_msg = (
        f"\n\n<i>Você ainda tem <b>{pending}</b> matéria(s) pendente(s) para revisar hoje.</i>"
        if pending > 0
        else "\n\n<i>Todas as revisões de hoje concluídas! 🎉</i>"
    )

    await message.answer(
        f"{result_icon} <b>Resultado:</b>\n\n{escape(feedback)}\n\n{interval_msg}{pending_msg}",
        parse_mode="HTML",
        reply_markup=review_feedback_kb(has_more=pending > 0),
    )


@router.message(Review.waiting_answer)
async def review_waiting_non_voice(message: Message) -> None:
    """Usuário mandou texto ou outro tipo quando esperava voice note."""
    await message.answer("Por favor, responda com um voice note 🎙️")
