"""Provedor Gemini para o study-talk — implementação multi-modelo."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from studytalk.llm.base import LLMProvider
from studytalk.llm.parsing import LLMParsingError, parse_llm_json
from studytalk.llm.prompts import (
    P1_PROMPT,
    P1_SYSTEM,
    P2_PROMPT,
    P2_SYSTEM,
    P3_PROMPT,
    P3_SYSTEM,
    P4_PROMPT,
    P4_SYSTEM,
    P5_PROMPT,
    P5_SYSTEM,
    P6_PROMPT,
    P6_SYSTEM,
    P7_PROMPT,
    P7_SYSTEM,
    _LEGACY_EVALUATE_ANSWER_PROMPT,
    _LEGACY_REVIEW_QUESTION_PROMPT,
)

logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    """Implementação do LLMProvider usando Google Gemini.

    Utiliza 5 modelos distintos otimizados por tipo de tarefa:
      multimodal — P1 e P6 (processa áudio)
      text_fast  — P2 e P3 (texto; alta quota)
      summary    — P4 (texto; resumos)
      questions  — P5 (texto; criação de perguntas; quota menor)
      reasoning  — P7 (texto; raciocínio pedagógico; quota menor)
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash-lite",
        model_multimodal: str = "gemini-2.0-flash-lite",
        model_text_fast: str = "gemini-2.0-flash-lite",
        model_summary: str = "gemini-2.0-flash-lite",
        model_questions: str = "gemini-2.5-flash",
        model_reasoning: str = "gemini-2.5-flash",
    ) -> None:
        if not api_key:
            raise ValueError("GEMINI_API_KEY não configurada")
        self._client = genai.Client(api_key=api_key)
        self._model = model  # legado

        self._models: dict[str, str] = {
            "multimodal": model_multimodal,
            "text_fast": model_text_fast,
            "summary": model_summary,
            "questions": model_questions,
            "reasoning": model_reasoning,
        }

    # ------------------------------------------------------------------
    # Utilitários privados
    # ------------------------------------------------------------------

    def _mime_for(self, audio_path: Path) -> str:
        return {
            ".ogg": "audio/ogg",
            ".oga": "audio/ogg",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".m4a": "audio/mp4",
            ".webm": "audio/webm",
        }.get(audio_path.suffix.lower(), "audio/ogg")

    def _upload_audio(self, audio_path: Path) -> Any:
        """Faz upload do arquivo de áudio para a API do Gemini."""
        mime = self._mime_for(audio_path)
        return self._client.files.upload(
            file=str(audio_path),
            config=types.UploadFileConfig(mime_type=mime),
        )

    def _call_gemini(
        self,
        model_key: str,
        contents: list[Any],
        system_instruction: str | None = None,
    ) -> str:
        """Método central de chamada ao Gemini.

        Args:
            model_key: Chave no dict ``_models`` ("multimodal", "text_fast",
                "summary", "questions", "reasoning").
            contents: Lista de conteúdos — pode misturar strings e arquivos
                uploaded via ``_upload_audio``.
            system_instruction: System prompt opcional.

        Returns:
            Texto da resposta (stripped), nunca vazio.

        Raises:
            KeyError: Se ``model_key`` não existir em ``_models``.
            RuntimeError: Se o Gemini retornar resposta vazia.
        """
        model = self._models[model_key]
        config = None
        if system_instruction:
            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
            )

        kwargs: dict[str, Any] = {
            "contents": contents,
        }
        if config is not None:
            kwargs["config"] = config

        candidates = [model]
        if model_key == "questions":
            for alt in (self._models["reasoning"], self._models["summary"]):
                if alt not in candidates:
                    candidates.append(alt)
        elif model_key == "reasoning":
            alt = self._models["summary"]
            if alt not in candidates:
                candidates.append(alt)

        last_error: Exception | None = None
        for candidate in candidates:
            for attempt in range(2):
                try:
                    response = self._client.models.generate_content(
                        model=candidate, **kwargs
                    )
                    text = (response.text or "").strip()
                    if not text:
                        raise RuntimeError(
                            f"Gemini ({candidate}) retornou resposta vazia "
                            f"(model_key={model_key!r})"
                        )
                    if candidate != model:
                        logger.warning(
                            "Gemini fallback: %s → %s (model_key=%s)",
                            model,
                            candidate,
                            model_key,
                        )
                    return text
                except Exception as exc:
                    last_error = exc
                    msg = str(exc)
                    overloaded = "503" in msg or "UNAVAILABLE" in msg or "high demand" in msg.lower()
                    if overloaded and attempt == 0:
                        logger.warning(
                            "Gemini sobrecarregado (%s, tentativa %s), retentando…",
                            candidate,
                            attempt + 1,
                        )
                        time.sleep(2)
                        continue
                    break
        assert last_error is not None
        raise last_error

    # ------------------------------------------------------------------
    # P1 — Análise Multimodal
    # ------------------------------------------------------------------

    def _sync_analyze_audio_multimodal(
        self,
        audio_path: Path,
        subject: str,
        lesson_number: int,
        accumulated_topics: str,
    ) -> dict[str, Any]:
        prompt = P1_PROMPT.format(
            subject=subject,
            lesson_number=lesson_number,
            accumulated_topics=accumulated_topics or "Nenhum tópico anterior registrado.",
        )
        uploaded = self._upload_audio(audio_path)
        raw = self._call_gemini(
            model_key="multimodal",
            contents=[prompt, uploaded],
            system_instruction=P1_SYSTEM,
        )
        return parse_llm_json(
            raw,
            required_fields=[
                "topic",
                "full_transcript",
                "concepts_mentioned",
                "student_clarity_score",
            ],
            context="P1-analyze_audio_multimodal",
        )

    async def analyze_audio_multimodal(
        self,
        audio_path: Path,
        subject: str,
        lesson_number: int,
        accumulated_topics: str,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._sync_analyze_audio_multimodal,
            audio_path,
            subject,
            lesson_number,
            accumulated_topics,
        )

    # ------------------------------------------------------------------
    # P2 — Extração de Conhecimento
    # ------------------------------------------------------------------

    def _sync_extract_lesson_knowledge(
        self,
        subject: str,
        lesson_number: int,
        p1_output: str,
        current_knowledge_map: str,
    ) -> dict[str, Any]:
        prompt = P2_PROMPT.format(
            subject=subject,
            lesson_number=lesson_number,
            p1_output=p1_output,
            current_knowledge_map=current_knowledge_map or "{}",
        )
        raw = self._call_gemini(
            model_key="text_fast",
            contents=[prompt],
            system_instruction=P2_SYSTEM,
        )
        return parse_llm_json(
            raw,
            required_fields=["lesson_topic", "knowledge_type", "concepts"],
            context="P2-extract_lesson_knowledge",
        )

    async def extract_lesson_knowledge(
        self,
        subject: str,
        lesson_number: int,
        p1_output: str,
        current_knowledge_map: str,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._sync_extract_lesson_knowledge,
            subject,
            lesson_number,
            p1_output,
            current_knowledge_map,
        )

    # ------------------------------------------------------------------
    # P3 — Atualização do Mapa de Conhecimento
    # ------------------------------------------------------------------

    def _sync_update_knowledge_map(
        self,
        subject: str,
        lesson_number: int,
        current_knowledge_map: str,
        new_lesson_knowledge: str,
    ) -> dict[str, Any]:
        prompt = P3_PROMPT.format(
            subject=subject,
            lesson_number=lesson_number,
            current_knowledge_map=current_knowledge_map or "{}",
            new_lesson_knowledge=new_lesson_knowledge,
        )
        raw = self._call_gemini(
            model_key="text_fast",
            contents=[prompt],
            system_instruction=P3_SYSTEM,
        )
        return parse_llm_json(
            raw,
            required_fields=["subject", "concepts", "topic_sequence"],
            context="P3-update_knowledge_map",
        )

    async def update_knowledge_map(
        self,
        subject: str,
        lesson_number: int,
        current_knowledge_map: str,
        new_lesson_knowledge: str,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._sync_update_knowledge_map,
            subject,
            lesson_number,
            current_knowledge_map,
            new_lesson_knowledge,
        )

    # ------------------------------------------------------------------
    # P4 — Resumo Pedagógico
    # ------------------------------------------------------------------

    def _sync_generate_pedagogical_summary(
        self,
        subject: str,
        lesson_number: int,
        knowledge_map_overview: str,
        topic_sequence: str,
        structured_concepts: str,
        student_clarity_score: int,
        student_clarity_justification: str,
    ) -> str:
        prompt = P4_PROMPT.format(
            subject=subject,
            lesson_number=lesson_number,
            knowledge_map_overview=knowledge_map_overview,
            topic_sequence=topic_sequence,
            structured_concepts=structured_concepts,
            student_clarity_score=student_clarity_score,
            student_clarity_justification=student_clarity_justification,
            materia=subject.lower().replace(" ", "_"),
            topico="topico",
        )
        return self._call_gemini(
            model_key="summary",
            contents=[prompt],
            system_instruction=P4_SYSTEM,
        )

    async def generate_pedagogical_summary(
        self,
        subject: str,
        lesson_number: int,
        knowledge_map_overview: str,
        topic_sequence: str,
        structured_concepts: str,
        student_clarity_score: int,
        student_clarity_justification: str,
    ) -> str:
        return await asyncio.to_thread(
            self._sync_generate_pedagogical_summary,
            subject,
            lesson_number,
            knowledge_map_overview,
            topic_sequence,
            structured_concepts,
            student_clarity_score,
            student_clarity_justification,
        )

    # ------------------------------------------------------------------
    # P5 — Banco de Perguntas
    # ------------------------------------------------------------------

    def _sync_generate_question_bank(
        self,
        subject: str,
        lesson_number: int,
        student_mastery_summary: str,
        structured_concepts: str,
        knowledge_map: str,
    ) -> dict[str, Any]:
        prompt = P5_PROMPT.format(
            subject=subject,
            lesson_number=lesson_number,
            student_mastery_summary=student_mastery_summary or "Primeira aula.",
            structured_concepts=structured_concepts,
            knowledge_map=knowledge_map or "{}",
        )
        raw = self._call_gemini(
            model_key="questions",
            contents=[prompt],
            system_instruction=P5_SYSTEM,
        )
        return parse_llm_json(
            raw,
            required_fields=["questions"],
            context="P5-generate_question_bank",
        )

    async def generate_question_bank(
        self,
        subject: str,
        lesson_number: int,
        student_mastery_summary: str,
        structured_concepts: str,
        knowledge_map: str,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._sync_generate_question_bank,
            subject,
            lesson_number,
            student_mastery_summary,
            structured_concepts,
            knowledge_map,
        )

    # ------------------------------------------------------------------
    # P6 — Avaliação de Resposta em Áudio
    # ------------------------------------------------------------------

    def _sync_evaluate_audio_answer_v2(
        self,
        audio_path: Path,
        question_type: str,
        question_text: str,
        expected_answer_criteria: str,
        concept_context: str,
        student_error_history: str,
    ) -> dict[str, Any]:
        prompt = P6_PROMPT.format(
            question_type=question_type,
            question_text=question_text,
            expected_answer_criteria=expected_answer_criteria,
            concept_context=concept_context,
            student_error_history=student_error_history or "Nenhum histórico.",
        )
        uploaded = self._upload_audio(audio_path)
        raw = self._call_gemini(
            model_key="multimodal",
            contents=[prompt, uploaded],
            system_instruction=P6_SYSTEM,
        )
        return parse_llm_json(
            raw,
            required_fields=[
                "transcript_of_answer",
                "overall_score",
                "feedback_to_student",
                "suggested_next_action",
            ],
            context="P6-evaluate_audio_answer_v2",
        )

    async def evaluate_audio_answer_v2(
        self,
        audio_path: Path,
        question_type: str,
        question_text: str,
        expected_answer_criteria: str,
        concept_context: str,
        student_error_history: str,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._sync_evaluate_audio_answer_v2,
            audio_path,
            question_type,
            question_text,
            expected_answer_criteria,
            concept_context,
            student_error_history,
        )

    # ------------------------------------------------------------------
    # P7 — Decisão Pedagógica
    # ------------------------------------------------------------------

    def _sync_decide_next_action(
        self,
        evaluation: str,
        question_type: str,
        question_difficulty: str,
        question_asked: str,
        session_history: str,
        available_questions: str,
        knowledge_map_overview: str,
    ) -> dict[str, Any]:
        prompt = P7_PROMPT.format(
            evaluation=evaluation,
            question_type=question_type,
            question_difficulty=question_difficulty,
            question_asked=question_asked,
            session_history=session_history or "Primeira pergunta da sessão.",
            available_questions=available_questions or "[]",
            knowledge_map_overview=knowledge_map_overview,
        )
        raw = self._call_gemini(
            model_key="reasoning",
            contents=[prompt],
            system_instruction=P7_SYSTEM,
        )
        return parse_llm_json(
            raw,
            required_fields=["reasoning", "action", "content", "session_should_end_after_this"],
            context="P7-decide_next_action",
        )

    async def decide_next_action(
        self,
        evaluation: str,
        question_type: str,
        question_difficulty: str,
        question_asked: str,
        session_history: str,
        available_questions: str,
        knowledge_map_overview: str,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._sync_decide_next_action,
            evaluation,
            question_type,
            question_difficulty,
            question_asked,
            session_history,
            available_questions,
            knowledge_map_overview,
        )

    # ------------------------------------------------------------------
    # Métodos legados — mantidos funcionando para compatibilidade
    # ------------------------------------------------------------------

    def _generate_with_audio(
        self, prompt: str, audio_path: Path, model: str | None = None
    ) -> str:
        """[LEGADO] Gera conteúdo com áudio usando o modelo legado."""
        mime = self._mime_for(audio_path)
        uploaded = self._client.files.upload(
            file=str(audio_path),
            config=types.UploadFileConfig(mime_type=mime),
        )
        response = self._client.models.generate_content(
            model=model or self._model,
            contents=[prompt, uploaded],
        )
        text = (response.text or "").strip()
        if not text:
            raise RuntimeError("Gemini retornou resposta vazia")
        return text

    def _generate_text(self, prompt: str, model: str | None = None) -> str:
        """[LEGADO] Gera conteúdo de texto usando o modelo legado."""
        response = self._client.models.generate_content(
            model=model or self._model,
            contents=prompt,
        )
        text = (response.text or "").strip()
        if not text:
            raise RuntimeError("Gemini retornou resposta vazia")
        return text

    async def process_audio_to_summary(
        self, audio_path: Path, subject: str, prompt: str
    ) -> str:
        """[LEGADO] Processa áudio + prompt → resumo em texto."""
        return await asyncio.to_thread(self._generate_with_audio, prompt, audio_path)

    async def generate_review_question(self, summary: str) -> str:
        """[LEGADO] Gera pergunta de revisão a partir do resumo."""
        prompt = _LEGACY_REVIEW_QUESTION_PROMPT.format(summary=summary)
        return await asyncio.to_thread(self._generate_text, prompt)

    async def evaluate_audio_answer(
        self, audio_path: Path, summary: str, question: str
    ) -> dict:
        """[LEGADO] Avalia resposta em áudio → {feedback: str, score: int}."""
        prompt = _LEGACY_EVALUATE_ANSWER_PROMPT.format(
            summary=summary, question=question
        )
        raw = await asyncio.to_thread(self._generate_with_audio, prompt, audio_path)

        feedback = raw
        score = 0
        lines = raw.splitlines()
        feedback_lines: list[str] = []
        for line in lines:
            upper = line.strip().upper()
            if upper.startswith("SCORE:"):
                score = 1 if "1" in line.split(":", 1)[-1] else 0
            elif upper.startswith("FEEDBACK:"):
                feedback_lines.append(line.split(":", 1)[-1].strip())
            else:
                feedback_lines.append(line)
        if feedback_lines:
            feedback = "\n".join(feedback_lines).strip()
        return {"feedback": feedback, "score": score}
