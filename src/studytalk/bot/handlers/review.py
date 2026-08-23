"""Handler de revisão — loop pedagógico multi-turn com banco de perguntas."""
from __future__ import annotations

import json
import logging
import tempfile
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import or_, select

from studytalk.bot.keyboards import main_menu_kb, post_review_kb, review_in_session_kb
from studytalk.bot.states import Review
from studytalk.bot.users import get_or_create_user
from studytalk.db.models import LessonNote, Question, ReviewSession, Subject, SubjectKnowledge
from studytalk.db.session import AsyncSessionLocal
from studytalk.llm.factory import get_llm_provider

router = Router(name="review")
logger = logging.getLogger(__name__)

BRAZIL_TZ = timezone(timedelta(hours=-3))
MAX_QUESTIONS_PER_SESSION = 5
QUESTION_COOLDOWN_HOURS = 72


# ─── Handlers públicos ────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:review")
async def start_review(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        user_id = user.id

    await _close_abandoned_sessions(user_id)

    due = await _due_subject(user_id)
    if due is None:
        info = await _next_review_info(user_id)
        await callback.message.answer(info, parse_mode="HTML", reply_markup=main_menu_kb())
        return

    subject_id, subject_name, _ = due
    due_note_ids = await _due_note_ids_for_subject(subject_id)
    if not due_note_ids:
        await callback.message.answer("Nenhuma revisão pendente.", reply_markup=main_menu_kb())
        return

    async with AsyncSessionLocal() as session:
        rs = ReviewSession(subject_id=subject_id, history_json="[]")
        session.add(rs)
        await session.commit()
        await session.refresh(rs)
        session_id = rs.id

    question = await _select_next_question(
        subject_id=subject_id,
        session_history=[],
        preferred_difficulty=None,
        preferred_concept=None,
        action=None,
    )

    if question is None:
        question = await _generate_question_fallback(subject_id, due_note_ids)
        if question is None:
            await callback.message.answer(
                "Não há perguntas disponíveis para esta matéria ainda. "
                "Envie mais aulas para gerar perguntas.",
                reply_markup=main_menu_kb(),
            )
            return

    await _mark_question_asked(question.id)

    await state.set_state(Review.waiting_answer)
    await state.update_data(
        user_id=user_id,
        subject_id=subject_id,
        subject_name=subject_name,
        session_id=session_id,
        current_question_id=question.id,
        current_question_text=question.question_text,
        current_question_topic=question.target_concept,
        question_count=1,
        session_history=[],
        due_note_ids=due_note_ids,
    )

    await _send_question(
        callback.message,
        question=question,
        subject_name=subject_name,
        question_number=1,
    )


@router.message(Review.waiting_answer, F.voice)
async def receive_review_answer(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    subject_id: int = data["subject_id"]
    subject_name: str = data["subject_name"]
    session_id: int = data["session_id"]
    current_q_id: int = data["current_question_id"]
    current_q_text: str = data["current_question_text"]
    question_count: int = data["question_count"]
    session_history: list = data["session_history"]
    due_note_ids: list[int] = data["due_note_ids"]
    user_id: int = data["user_id"]

    await message.answer("⏳ Avaliando sua resposta…")

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        await message.bot.download(message.voice.file_id, destination=tmp_path)

        question_obj = await _get_question(current_q_id)
        answer_criteria_raw = {}
        if question_obj and question_obj.answer_criteria:
            try:
                answer_criteria_raw = json.loads(question_obj.answer_criteria)
            except (json.JSONDecodeError, TypeError):
                answer_criteria_raw = {}
        if isinstance(answer_criteria_raw, dict) and "expected_answer_criteria" in answer_criteria_raw:
            criteria_payload = answer_criteria_raw["expected_answer_criteria"]
        else:
            criteria_payload = answer_criteria_raw
        concept_context = question_obj.target_concept if question_obj else ""
        error_history = await _get_error_history(subject_id, concept_context)
        question_type = question_obj.bloom_type if question_obj else "compreensão"
        question_difficulty = question_obj.difficulty if question_obj else "médio"

        provider = get_llm_provider()
        try:
            evaluation = await provider.evaluate_audio_answer_v2(
                audio_path=tmp_path,
                question_type=question_type,
                question_text=current_q_text,
                expected_answer_criteria=json.dumps(criteria_payload, ensure_ascii=False),
                concept_context=concept_context or "",
                student_error_history=error_history or "Nenhum erro anterior registrado.",
            )
            score: int = evaluation.get("overall_score", evaluation.get("overall_score", 0))
            gaps: list = evaluation.get("what_student_missed", evaluation.get("what_student_missed", []))
            feedback: str = evaluation.get("feedback_to_student", evaluation.get("feedback_to_student", ""))
        except Exception as exc:
            logger.exception("P6 falhou (session_id=%s): %s", session_id, exc)
            await message.answer(
                "Não consegui avaliar sua resposta agora. Tente enviar de novo.",
                reply_markup=review_in_session_kb(),
            )
            return

    except Exception as exc:
        logger.exception("Erro ao processar resposta (session_id=%s): %s", session_id, exc)
        await message.answer(
            "Erro ao processar o áudio. Tente de novo.",
            reply_markup=review_in_session_kb(),
        )
        return
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

    updated_history = session_history + [
        {"question_id": current_q_id, "score": score, "gaps": gaps}
    ]
    questions_remaining = MAX_QUESTIONS_PER_SESSION - question_count

    # P7 — Decisão pedagógica
    knowledge_overview = await _get_knowledge_overview(subject_id)
    available_questions_meta = await _get_available_questions_meta(
        subject_id, [h["question_id"] for h in updated_history]
    )
    try:
        decision = await provider.decide_next_action(
            evaluation=json.dumps(evaluation, ensure_ascii=False),
            question_type=question_type,
            question_difficulty=question_difficulty,
            question_asked=current_q_text,
            session_history=json.dumps(updated_history, ensure_ascii=False),
            available_questions=json.dumps(available_questions_meta, ensure_ascii=False),
            knowledge_map_overview=knowledge_overview,
        )
        action: str = decision.get("action", "close_session")
        should_end: bool = decision.get("session_should_end_after_this", False)
    except Exception as exc:
        logger.exception("P7 falhou (session_id=%s): %s", session_id, exc)
        action = "ask_harder" if (score >= 2 and questions_remaining > 0) else "close_session"
        decision = {
            "action": action,
            "content": {
                "message_to_student": "",
                "explanation_if_needed": "",
                "next_question_id": None,
            },
        }
        should_end = action == "close_session"

    await _send_answer_feedback(message, score=score, feedback=feedback, action=action)

    if question_count >= MAX_QUESTIONS_PER_SESSION or should_end or action == "close_session":
        await state.clear()
        await _close_session(
            message,
            session_id=session_id,
            subject_id=subject_id,
            subject_name=subject_name,
            due_note_ids=due_note_ids,
            user_id=user_id,
            session_history=updated_history,
        )
        return

    content = decision.get("content", {})
    if action in ("explain", "give_example") and content.get("explanation_if_needed"):
        await message.answer(content["explanation_if_needed"], parse_mode="HTML")

    preferred_difficulty = {"ask_easier": "fácil", "ask_harder": "difícil"}.get(action)
    preferred_concept = content.get("next_concept_hint")
    next_question_id = content.get("next_question_id")

    next_q = None
    if next_question_id not in (None, "", "null"):
        try:
            next_q = await _get_question(int(next_question_id))
        except (TypeError, ValueError):
            next_q = None

    if next_q is None:
        next_q = await _select_next_question(
            subject_id=subject_id,
            session_history=updated_history,
            preferred_difficulty=preferred_difficulty,
            preferred_concept=preferred_concept,
            action=action,
        )

    if next_q is None:
        await state.clear()
        await _close_session(
            message,
            session_id=session_id,
            subject_id=subject_id,
            subject_name=subject_name,
            due_note_ids=due_note_ids,
            user_id=user_id,
            session_history=updated_history,
        )
        return

    await _mark_question_asked(next_q.id, last_score=score)
    new_count = question_count + 1
    await state.update_data(
        current_question_id=next_q.id,
        current_question_text=next_q.question_text,
        current_question_topic=next_q.target_concept,
        question_count=new_count,
        session_history=updated_history,
    )
    await _send_question(
        message,
        question=next_q,
        subject_name=subject_name,
        question_number=new_count,
    )


@router.callback_query(Review.waiting_answer, F.data == "review:skip")
async def review_skip_question(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    subject_id = data["subject_id"]
    subject_name = data["subject_name"]
    session_id = data["session_id"]
    current_q_id = data["current_question_id"]
    question_count = data["question_count"]
    session_history = data["session_history"]
    due_note_ids = data["due_note_ids"]
    user_id = data["user_id"]

    updated_history = session_history + [
        {"question_id": current_q_id, "score": 0, "gaps": ["pulou"]}
    ]

    if question_count >= MAX_QUESTIONS_PER_SESSION:
        await state.clear()
        await _close_session(
            callback.message,
            session_id=session_id,
            subject_id=subject_id,
            subject_name=subject_name,
            due_note_ids=due_note_ids,
            user_id=user_id,
            session_history=updated_history,
        )
        return

    next_q = await _select_next_question(
        subject_id=subject_id,
        session_history=updated_history,
        preferred_difficulty=None,
        preferred_concept=None,
        action=None,
    )
    if next_q is None:
        await state.clear()
        await _close_session(
            callback.message,
            session_id=session_id,
            subject_id=subject_id,
            subject_name=subject_name,
            due_note_ids=due_note_ids,
            user_id=user_id,
            session_history=updated_history,
        )
        return

    await _mark_question_asked(next_q.id)
    new_count = question_count + 1
    await state.update_data(
        current_question_id=next_q.id,
        current_question_text=next_q.question_text,
        current_question_topic=next_q.target_concept,
        question_count=new_count,
        session_history=updated_history,
    )
    await _send_question(
        callback.message,
        question=next_q,
        subject_name=subject_name,
        question_number=new_count,
    )


@router.callback_query(Review.waiting_answer, F.data == "review:end_session")
async def review_end_session(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    await state.clear()
    await _close_session(
        callback.message,
        session_id=data["session_id"],
        subject_id=data["subject_id"],
        subject_name=data["subject_name"],
        due_note_ids=data["due_note_ids"],
        user_id=data["user_id"],
        session_history=data["session_history"],
    )


@router.message(Review.waiting_answer)
async def review_waiting_non_voice(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    question_text = data.get("current_question_text", "")
    topic = data.get("current_question_topic", "")
    count = data.get("question_count", 1)
    await message.answer(
        f"Por favor, responda com um voice note 🎙️\n\n"
        f"Pergunta atual ({count}/{MAX_QUESTIONS_PER_SESSION}):\n"
        f"<i>{escape(topic)}</i>\n\n{escape(question_text)}",
        parse_mode="HTML",
        reply_markup=review_in_session_kb(),
    )


# ─── Auxiliares internos ──────────────────────────────────────────────────────

async def _due_subject(user_id: int):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Subject.id, Subject.name, LessonNote.next_review_at)
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


async def _due_note_ids_for_subject(subject_id: int) -> list[int]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(LessonNote.id)
            .where(
                LessonNote.subject_id == subject_id,
                LessonNote.improved_summary.isnot(None),
                LessonNote.next_review_at <= datetime.now(timezone.utc),
            )
            .order_by(LessonNote.next_review_at.asc())
        )
        return [r[0] for r in result.all()]


async def _count_pending_subjects(user_id: int) -> int:
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


async def _select_next_question(
    subject_id: int,
    session_history: list,
    *,
    preferred_difficulty: str | None,
    preferred_concept: str | None,
    action: str | None,
) -> Question | None:
    asked_ids = {h["question_id"] for h in session_history}
    cooldown_cutoff = datetime.now(timezone.utc) - timedelta(hours=QUESTION_COOLDOWN_HOURS)

    async with AsyncSessionLocal() as session:
        filters = [
            Question.subject_id == subject_id,
            or_(Question.last_asked_at.is_(None), Question.last_asked_at < cooldown_cutoff),
        ]
        if asked_ids:
            filters.append(Question.id.notin_(asked_ids))
        result = await session.execute(select(Question).where(*filters))
        candidates = list(result.scalars().all())

    if not candidates:
        return None

    session_concepts = {h.get("concept", "") for h in session_history}

    def score_candidate(q: Question) -> float:
        s = 0.0
        if preferred_difficulty and q.difficulty == preferred_difficulty:
            s += 10.0
        if action == "ask_easier" and q.difficulty == "fácil":
            s += 8.0
        if action == "ask_harder" and q.difficulty == "difícil":
            s += 8.0
        if preferred_concept and preferred_concept.lower() in q.target_concept.lower():
            s += 6.0
        if q.times_asked == 0:
            s += 4.0
        if q.times_correct < q.times_asked and q.times_asked > 0:
            s += 3.0
        if q.target_concept not in session_concepts:
            s += 2.0
        if q.last_asked_at is not None:
            age_days = (datetime.now(timezone.utc) - q.last_asked_at).days
            s += min(age_days * 0.1, 1.0)
        return s

    candidates.sort(key=score_candidate, reverse=True)
    return candidates[0]


async def _generate_question_fallback(subject_id: int, due_note_ids: list[int]) -> Question | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(LessonNote).where(LessonNote.id.in_(due_note_ids))
        )
        notes = list(result.scalars().all())
    combined = "\n\n---\n\n".join(
        f"[Nota {i+1}]\n{n.improved_summary}" for i, n in enumerate(notes)
    )
    try:
        provider = get_llm_provider()
        question_text = await provider.generate_review_question(combined)
        async with AsyncSessionLocal() as session:
            q = Question(
                subject_id=subject_id,
                lesson_note_id=due_note_ids[0],
                question_text=question_text,
                bloom_type="compreensão",
                difficulty="médio",
                target_concept="",
                answer_criteria="{}",
            )
            session.add(q)
            await session.commit()
            await session.refresh(q)
            return q
    except Exception as exc:
        logger.exception("Fallback de pergunta falhou: %s", exc)
        return None


async def _get_question(question_id: int) -> Question | None:
    async with AsyncSessionLocal() as session:
        return await session.get(Question, question_id)


async def _mark_question_asked(question_id: int, last_score: int | None = None) -> None:
    async with AsyncSessionLocal() as session:
        q = await session.get(Question, question_id)
        if q:
            q.times_asked += 1
            if last_score is not None and last_score >= 2:
                q.times_correct += 1
            q.last_asked_at = datetime.now(timezone.utc)
            await session.commit()


async def _build_context_summary(note_ids: list[int]) -> str:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(LessonNote).where(LessonNote.id.in_(note_ids))
        )
        notes = list(result.scalars().all())
    return "\n\n---\n\n".join(
        f"[Nota {i+1}]\n{n.improved_summary}" for i, n in enumerate(notes)
    )


async def _get_error_history(subject_id: int, concept: str) -> str:
    if not concept:
        return ""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ReviewSession.identified_gaps)
            .where(
                ReviewSession.subject_id == subject_id,
                ReviewSession.identified_gaps.isnot(None),
                ReviewSession.identified_gaps.like(f'%{concept[:20]}%'),
            )
            .order_by(ReviewSession.reviewed_at.desc())
            .limit(5)
        )
        rows = result.all()
    if not rows:
        return ""
    gaps = []
    for row in rows:
        try:
            gaps.extend(json.loads(row[0]) if row[0] else [])
        except Exception:
            pass
    return ", ".join(set(gaps[:10])) if gaps else ""


async def _get_knowledge_overview(subject_id: int) -> str:
    async with AsyncSessionLocal() as session:
        sk = await session.scalar(
            select(SubjectKnowledge).where(SubjectKnowledge.subject_id == subject_id)
        )
    if sk is None:
        return "Nenhum mapa de conhecimento disponível ainda."
    try:
        km = json.loads(sk.knowledge_map)
        return km.get("discipline_overview", "Mapa de conhecimento disponível mas sem overview.")
    except Exception:
        return "Mapa de conhecimento disponível."


async def _get_available_questions_meta(subject_id: int, exclude_ids: list[int]) -> list[dict]:
    cooldown_cutoff = datetime.now(timezone.utc) - timedelta(hours=QUESTION_COOLDOWN_HOURS)
    async with AsyncSessionLocal() as session:
        filters = [
            Question.subject_id == subject_id,
            or_(Question.last_asked_at.is_(None), Question.last_asked_at < cooldown_cutoff),
        ]
        if exclude_ids:
            filters.append(Question.id.notin_(exclude_ids))
        result = await session.execute(
            select(
                Question.id,
                Question.bloom_type,
                Question.difficulty,
                Question.target_concept,
            )
            .where(*filters)
            .limit(20)
        )
        return [
            {"id": r[0], "type": r[1], "difficulty": r[2], "concept": r[3]}
            for r in result.all()
        ]


async def _close_session(
    message: Message,
    *,
    session_id: int,
    subject_id: int,
    subject_name: str,
    due_note_ids: list[int],
    user_id: int,
    session_history: list,
) -> None:
    now = datetime.now(timezone.utc)
    avg_score = (
        sum(h["score"] for h in session_history) / len(session_history)
        if session_history
        else 0.0
    )
    multiplier = 2.5 if avg_score >= 2.5 else (1.5 if avg_score >= 1.5 else None)

    async with AsyncSessionLocal() as session:
        rs = await session.get(ReviewSession, session_id)
        if rs:
            rs.reviewed_at = now
            rs.history_json = json.dumps(session_history, ensure_ascii=False)
            rs.score = round(avg_score)

        result = await session.execute(
            select(LessonNote).where(LessonNote.id.in_(due_note_ids))
        )
        notes = list(result.scalars().all())
        for note in notes:
            current_interval = note.review_interval_days or 1
            new_interval = max(1, int(current_interval * multiplier)) if multiplier else 1
            note.review_interval_days = new_interval
            note.next_review_at = now + timedelta(days=new_interval)

        await session.commit()

    score_label = (
        "Excelente 🌟" if avg_score >= 2.5
        else ("Bom 👍" if avg_score >= 1.5 else "Continue praticando 💪")
    )
    pending = await _count_pending_subjects(user_id)
    pending_msg = (
        f"\n\n<i>Você tem <b>{pending}</b> matéria(s) pendente(s) para revisar.</i>"
        if pending > 0
        else "\n\n<i>Todas as revisões do dia concluídas! 🎉</i>"
    )

    await message.answer(
        f"✅ <b>Sessão encerrada — {escape(subject_name)}</b>\n\n"
        f"Perguntas respondidas: <b>{len(session_history)}</b>\n"
        f"Desempenho: <b>{score_label}</b>{pending_msg}",
        parse_mode="HTML",
        reply_markup=post_review_kb(has_more=pending > 0, subject_id=subject_id),
    )


async def _close_abandoned_sessions(user_id: int) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ReviewSession)
            .join(Subject, Subject.id == ReviewSession.subject_id)
            .where(
                Subject.user_id == user_id,
                ReviewSession.reviewed_at.is_(None),
            )
        )
        now = datetime.now(timezone.utc)
        for rs in result.scalars().all():
            rs.reviewed_at = now
        await session.commit()


async def _send_question(
    message: Message,
    *,
    question: Question,
    subject_name: str,
    question_number: int,
) -> None:
    topic = escape(question.target_concept) if question.target_concept else "Geral"
    await message.answer(
        f"📖 <b>Revisão — {escape(subject_name)}</b>\n\n"
        f"❓ <b>Pergunta {question_number}/{MAX_QUESTIONS_PER_SESSION}</b>\n"
        f"Tópico: <i>{topic}</i>\n\n"
        f"{escape(question.question_text)}\n\n"
        "Responda com um voice note 🎙️",
        parse_mode="HTML",
        reply_markup=review_in_session_kb(),
    )


async def _send_answer_feedback(
    message: Message,
    *,
    score: int,
    feedback: str,
    action: str,
) -> None:
    icons = {0: "❌", 1: "🔶", 2: "✅", 3: "⭐"}
    icon = icons.get(score, "🔶")
    action_hints = {
        "explain": "\n\n💡 <i>Vou explicar melhor antes da próxima pergunta.</i>",
        "ask_easier": "\n\n📉 <i>Vamos tentar uma pergunta mais acessível.</i>",
        "ask_harder": "\n\n📈 <i>Ótimo! Vamos aprofundar.</i>",
        "give_example": "\n\n🔍 <i>Vou mostrar um exemplo concreto.</i>",
        "ask_connection": "\n\n🔗 <i>Vamos explorar conexões com outros tópicos.</i>",
        "ask_same_concept_different_angle": "\n\n🔄 <i>Vamos ver esse conceito de outro ângulo.</i>",
    }
    hint = action_hints.get(action, "")
    await message.answer(
        f"{icon} <b>Avaliação:</b>\n\n{escape(feedback)}{hint}",
        parse_mode="HTML",
    )
