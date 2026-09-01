"""Handler de voice notes de aula — pipeline P1→P4 + P5 em background."""
from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func as sa_func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from studytalk.bot.keyboards import new_subject_kb, subjects_list_kb
from studytalk.bot.states import LinkNote, Review
from studytalk.bot.users import get_or_create_user
from studytalk.config import settings
from studytalk.db.models import LessonNote, Question, Subject, SubjectKnowledge
from studytalk.db.session import AsyncSessionLocal
from studytalk.llm.factory import get_llm_provider

router = Router(name="notes")
logger = logging.getLogger(__name__)

_VALID_KNOWLEDGE_TYPES = frozenset({"novo", "revisão", "aprofundamento", "aplicação"})
_VALID_BLOOM_TYPES = frozenset({
    "memorização", "compreensão", "aplicação", "raciocínio",
    "identificação_de_erros", "conexão",
})
_VALID_DIFFICULTIES = frozenset({"fácil", "médio", "difícil"})


# ─── Handlers públicos ────────────────────────────────────────────────────────

# Voice notes durante Review.waiting_answer são tratados por
# `review.receive_review_answer` (registrado depois deste router em main.py).
# Este router só deve capturar áudios de aula, por isso o filtro abaixo
# exclui explicitamente o estado de revisão — sem essa exclusão, este
# handler intercepta a resposta antes do router de revisão e ela nunca
# chega a ser avaliada.
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

        lesson_num = await _next_lesson_number(session, subject_id)

        note = LessonNote(
            subject_id=subject.id,
            user_audio_file_id=file_id,
            improved_summary=None,
            lesson_number=lesson_num,
        )
        session.add(note)
        await session.commit()
        await session.refresh(note)
        note_id = note.id
        subject_name = subject.name

    await state.clear()
    await callback.message.answer(f"Áudio salvo em {subject_name} ✓")

    asyncio.create_task(
        _run_note_pipeline(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            note_id=note_id,
            file_id=file_id,
            subject_id=subject_id,
            subject_name=subject_name,
            lesson_number=lesson_num,
        )
    )


@router.callback_query(F.data.startswith("link:"))
async def link_without_pending(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer("Envie um voice note primeiro para vincular à matéria.")


# ─── Pipeline principal ───────────────────────────────────────────────────────

async def _run_note_pipeline(
    *,
    bot: Bot,
    chat_id: int,
    note_id: int,
    file_id: str,
    subject_id: int,
    subject_name: str,
    lesson_number: int,
) -> None:
    tmp_path: Path | None = None
    try:
        tmp_path = await _download_audio(bot, file_id)
        provider = get_llm_provider()

        # P1 — Análise multimodal
        await bot.send_message(chat_id, "🔍 Analisando áudio…")
        accumulated_topics = await _get_accumulated_topics(subject_id)
        try:
            analysis = await provider.analyze_audio_multimodal(
                tmp_path, subject_name, lesson_number, accumulated_topics
            )
        except Exception as exc:
            await _handle_pipeline_error(bot, chat_id, "análise do áudio", exc, note_id)
            return

        # Análise P1 fica em memória; raw_transcript/topic salvos após P4
        logger.debug("P1 analysis keys: %s", list(analysis.keys()) if isinstance(analysis, dict) else type(analysis))

        # P2 — Extração estruturada
        await bot.send_message(chat_id, "📚 Extraindo conceitos…")
        current_map = await _load_knowledge_map(subject_id)
        current_map_json = json.dumps(current_map, ensure_ascii=False) if current_map else ""
        try:
            knowledge = await provider.extract_lesson_knowledge(
                subject_name,
                lesson_number,
                json.dumps(analysis, ensure_ascii=False),
                current_map_json,
            )
        except Exception as exc:
            await _handle_pipeline_error(bot, chat_id, "extração de conceitos", exc, note_id)
            return

        await _save_note_fields(note_id, structured_concepts=json.dumps(knowledge, ensure_ascii=False))

        # P3 — Atualização do mapa (degradação graciosa)
        try:
            updated_map = await provider.update_knowledge_map(
                subject_name,
                lesson_number,
                current_map_json,
                json.dumps(knowledge, ensure_ascii=False),
            )
            await _save_knowledge_map(subject_id, updated_map, lesson_number)
        except Exception as exc:
            logger.warning("P3 falhou, continuando sem atualizar mapa: %s", exc)
            updated_map = current_map

        # P4 — Resumo pedagógico
        await bot.send_message(chat_id, "✍️ Gerando resumo…")
        overview = ""
        if isinstance(updated_map, dict):
            overview = updated_map.get("discipline_overview") or updated_map.get("discipline_overview") or ""
        topic_seq_raw = []
        if isinstance(updated_map, dict):
            topic_seq_raw = updated_map.get("topic_sequence") or updated_map.get("topic_sequence") or []
        if isinstance(topic_seq_raw, list):
            topic_sequence = "\n".join(f"- {t}" for t in topic_seq_raw) if topic_seq_raw else "Nenhum tópico anterior."
        else:
            topic_sequence = str(topic_seq_raw or "Nenhum tópico anterior.")
        clarity_score = analysis.get("student_clarity_score", analysis.get("student_clarity_score", 2))
        clarity_just = analysis.get("student_clarity_justification", analysis.get("student_clarity_justification", ""))
        try:
            summary_html = await provider.generate_pedagogical_summary(
                subject_name,
                lesson_number,
                overview or "Mapa de conhecimento ainda em construção.",
                topic_sequence,
                json.dumps(knowledge, ensure_ascii=False),
                int(clarity_score) if clarity_score is not None else 2,
                clarity_just or "",
            )
        except Exception as exc:
            await _handle_pipeline_error(bot, chat_id, "geração do resumo", exc, note_id)
            return

        next_review = datetime.now(timezone.utc) + timedelta(days=1)
        knowledge_type = knowledge.get("knowledge_type") or knowledge.get("knowledge_type") or "novo"
        if knowledge_type not in _VALID_KNOWLEDGE_TYPES:
            knowledge_type = "novo"
        async with AsyncSessionLocal() as session:
            note = await session.get(LessonNote, note_id)
            if note:
                note.improved_summary = summary_html
                note.next_review_at = next_review
                note.review_interval_days = 1
                note.detected_topic = analysis.get("topic", "")
                note.student_clarity_score = clarity_score
                note.knowledge_type = knowledge_type
                note.raw_transcript = (
                    analysis.get("full_transcript") or analysis.get("full_transcript") or ""
                )[:10000]
                await session.commit()

        await _send_summary(bot, chat_id, subject_name=subject_name, summary=summary_html)

        # P5 — Banco de perguntas (background)
        asyncio.create_task(
            _generate_and_save_questions(
                provider=provider,
                note_id=note_id,
                subject_id=subject_id,
                subject_name=subject_name,
                knowledge=knowledge,
                knowledge_map=updated_map,
                lesson_number=lesson_number,
            )
        )

    except Exception as exc:
        logger.exception("Pipeline falhou (note_id=%s): %s", note_id, exc)
        try:
            await bot.send_message(chat_id, "Ocorreu um erro inesperado no processamento. O áudio está salvo.")
        except Exception:
            pass
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


async def _generate_and_save_questions(
    *,
    provider,
    note_id: int,
    subject_id: int,
    subject_name: str,
    knowledge: dict,
    knowledge_map: dict,
    lesson_number: int,
) -> None:
    try:
        mastery_summary = _build_mastery_summary(knowledge_map)
        questions_data = await provider.generate_question_bank(
            subject_name,
            lesson_number,
            mastery_summary,
            json.dumps(knowledge, ensure_ascii=False),
            json.dumps(knowledge_map, ensure_ascii=False),
        )
        if isinstance(questions_data, dict):
            questions_list = questions_data.get("questions", [])
        else:
            questions_list = questions_data or []
        async with AsyncSessionLocal() as session:
            for q in questions_list:
                bloom = q.get("type", "compreensão")
                if bloom not in _VALID_BLOOM_TYPES:
                    bloom = "compreensão"
                difficulty = q.get("difficulty", "médio")
                if difficulty not in _VALID_DIFFICULTIES:
                    difficulty = "médio"
                question = Question(
                    subject_id=subject_id,
                    lesson_note_id=note_id,
                    question_text=q.get("question_text") or q.get("question_text") or "",
                    bloom_type=bloom,
                    difficulty=difficulty,
                    target_concept=q.get("concept_target") or q.get("concept_target") or "",
                    answer_criteria=json.dumps(
                        {
                            "expected_answer_criteria": q.get("expected_answer_criteria")
                            or q.get("expected_answer_criteria")
                            or [],
                            "common_wrong_answers": q.get("common_wrong_answers")
                            or q.get("common_wrong_answers")
                            or [],
                            "follow_up_if_wrong": q.get("follow_up_if_wrong", ""),
                        },
                        ensure_ascii=False,
                    ),
                )
                session.add(question)
            await session.commit()
        logger.info("Banco de perguntas gerado: %d questões (note_id=%s)", len(questions_list), note_id)
    except Exception as exc:
        logger.exception("Falha ao gerar banco de perguntas (note_id=%s): %s", note_id, exc)


# ─── Auxiliares ───────────────────────────────────────────────────────────────

async def _download_audio(bot: Bot, file_id: str) -> Path:
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    await bot.download(file_id, destination=tmp_path)
    return tmp_path


async def _next_lesson_number(session, subject_id: int) -> int:
    result = await session.scalar(
        select(sa_func.coalesce(sa_func.max(LessonNote.lesson_number), 0))
        .where(LessonNote.subject_id == subject_id)
    )
    return (result or 0) + 1


async def _get_accumulated_topics(subject_id: int) -> str:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(LessonNote.lesson_number, LessonNote.detected_topic)
            .where(
                LessonNote.subject_id == subject_id,
                LessonNote.detected_topic.isnot(None),
            )
            .order_by(LessonNote.lesson_number.asc())
        )
        rows = result.all()
    if not rows:
        return "Nenhuma aula anterior registrada."
    return "\n".join(f"Aula {r[0]}: {r[1]}" for r in rows if r[1])


async def _load_knowledge_map(subject_id: int) -> dict:
    async with AsyncSessionLocal() as session:
        sk = await session.scalar(
            select(SubjectKnowledge).where(SubjectKnowledge.subject_id == subject_id)
        )
    if sk is None:
        return {}
    try:
        return json.loads(sk.knowledge_map)
    except (json.JSONDecodeError, TypeError):
        return {}


async def _save_knowledge_map(subject_id: int, content: dict, lesson_number: int) -> None:
    async with AsyncSessionLocal() as session:
        stmt = (
            sqlite_insert(SubjectKnowledge)
            .values(
                subject_id=subject_id,
                knowledge_map=json.dumps(content, ensure_ascii=False),
                last_lesson_number=lesson_number,
                last_updated_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_update(
                index_elements=["subject_id"],
                set_={
                    "knowledge_map": json.dumps(content, ensure_ascii=False),
                    "last_lesson_number": lesson_number,
                    "last_updated_at": datetime.now(timezone.utc),
                },
            )
        )
        await session.execute(stmt)
        await session.commit()


async def _save_note_fields(note_id: int, **kwargs) -> None:
    async with AsyncSessionLocal() as session:
        note = await session.get(LessonNote, note_id)
        if note:
            for k, v in kwargs.items():
                setattr(note, k, v)
            await session.commit()


def _build_mastery_summary(knowledge_map: dict) -> str:
    concepts = knowledge_map.get("concepts", {})
    if not concepts:
        return "Nenhum conceito registrado ainda."
    lines = []
    for key, data in list(concepts.items())[:20]:
        mastery = data.get("student_mastery", "não visto")
        label = data.get("name", key)
        lines.append(f"- {label}: {mastery}")
    return "\n".join(lines)


async def _handle_pipeline_error(
    bot: Bot,
    chat_id: int,
    stage_name: str,
    exc: Exception,
    note_id: int,
) -> None:
    logger.exception("Pipeline — %s falhou (note_id=%s): %s", stage_name, note_id, exc)
    err = str(exc).lower()
    if "429" in err or "quota" in err or "rate" in err or "resource_exhausted" in err:
        msg = f"A IA está ocupada durante {stage_name}. Tente de novo em alguns minutos. O áudio continua salvo."
    elif "404" in err or "not_found" in err or "no longer available" in err:
        msg = f"Modelo de IA indisponível durante {stage_name}. Verifique GEMINI_MODEL no .env. O áudio continua salvo."
    else:
        msg = f"Não consegui completar {stage_name} agora. O áudio continua salvo — tente enviar de novo mais tarde."
    try:
        await bot.send_message(chat_id, msg)
    except Exception:
        pass


async def _send_summary(bot: Bot, chat_id: int, *, subject_name: str, summary: str) -> None:
    header = f"📝 Resumo — {escape(subject_name)}"
    text = f"{header}\n\n{summary}"
    try:
        await bot.send_message(chat_id, text, parse_mode="HTML")
    except TelegramBadRequest:
        logger.warning("Resumo com HTML inválido; reenviando em texto puro")
        await bot.send_message(chat_id, f"📝 Resumo — {subject_name}\n\n{summary}")
