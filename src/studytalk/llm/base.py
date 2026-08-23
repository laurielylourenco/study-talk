"""Interface abstrata para provedores de LLM do study-talk."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class LLMProvider(ABC):
    """Contrato que todo provedor de LLM deve implementar.

    Métodos P1–P7 correspondem ao pipeline pedagógico:
      P1  analyze_audio_multimodal      — transcrição + análise inicial
      P2  extract_lesson_knowledge      — estruturação do conhecimento da aula
      P3  update_knowledge_map          — merge no mapa acumulado da disciplina
      P4  generate_pedagogical_summary  — resumo HTML para o Telegram
      P5  generate_question_bank        — banco de perguntas de revisão
      P6  evaluate_audio_answer_v2      — avaliação da resposta em áudio
      P7  decide_next_action            — decisão pedagógica do próximo passo

    Métodos legados (mantidos para compatibilidade):
      process_audio_to_summary   — levanta NotImplementedError
      generate_review_question   — levanta NotImplementedError
      evaluate_audio_answer      — levanta NotImplementedError
    """

    # ------------------------------------------------------------------
    # P1 — Análise Multimodal
    # ------------------------------------------------------------------

    @abstractmethod
    async def analyze_audio_multimodal(
        self,
        audio_path: Path,
        subject: str,
        lesson_number: int,
        accumulated_topics: str,
    ) -> dict[str, Any]:
        """Transcreve e analisa o áudio de estudo do aluno.

        Args:
            audio_path: Caminho para o arquivo de áudio.
            subject: Nome da matéria (ex.: "Física").
            lesson_number: Número sequencial da aula na matéria.
            accumulated_topics: String descrevendo tópicos das aulas anteriores
                ou "Nenhum" se for a primeira aula.

        Returns:
            dict com as chaves:
                topic (str), subtopics (list[str]),
                full_transcript (str), clean_summary_transcript (str),
                concepts_mentioned (list[dict]),
                is_continuation_of (str | None),
                student_clarity_score (int 0-3),
                student_clarity_justification (str),
                flags (list[str])
        """

    # ------------------------------------------------------------------
    # P2 — Extração de Conhecimento
    # ------------------------------------------------------------------

    @abstractmethod
    async def extract_lesson_knowledge(
        self,
        subject: str,
        lesson_number: int,
        p1_output: str,
        current_knowledge_map: str,
    ) -> dict[str, Any]:
        """Estrutura o conhecimento da aula a partir da análise P1.

        Args:
            subject: Nome da matéria.
            lesson_number: Número sequencial da aula.
            p1_output: JSON (como string) retornado pelo P1.
            current_knowledge_map: JSON (como string) do mapa de conhecimento
                acumulado, ou string vazia se for a primeira aula.

        Returns:
            dict com as chaves:
                lesson_topic (str), knowledge_type (str),
                knowledge_type_justification (str),
                concepts (list[dict]),
                new_concepts (list[str]), reviewed_concepts (list[str]),
                deepened_concepts (list[str]),
                key_relationships (list[dict]),
                missing_prerequisites (list[dict])
        """

    # ------------------------------------------------------------------
    # P3 — Atualização do Mapa de Conhecimento
    # ------------------------------------------------------------------

    @abstractmethod
    async def update_knowledge_map(
        self,
        subject: str,
        lesson_number: int,
        current_knowledge_map: str,
        new_lesson_knowledge: str,
    ) -> dict[str, Any]:
        """Faz merge do conhecimento da nova aula no mapa acumulado.

        Args:
            subject: Nome da matéria.
            lesson_number: Número sequencial da aula.
            current_knowledge_map: JSON (como string) do mapa atual,
                ou string vazia se for a primeira aula.
            new_lesson_knowledge: JSON (como string) retornado pelo P2.

        Returns:
            dict com o mapa de conhecimento completo atualizado, com as chaves:
                subject (str), total_lessons_processed (int),
                last_updated_lesson (str), topic_sequence (list[str]),
                concepts (dict), concept_relationships (list[dict]),
                learning_gaps_detected (list), discipline_overview (str)
        """

    # ------------------------------------------------------------------
    # P4 — Resumo Pedagógico
    # ------------------------------------------------------------------

    @abstractmethod
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
        """Gera o resumo da aula formatado em HTML do Telegram.

        Args:
            subject: Nome da matéria.
            lesson_number: Número sequencial da aula.
            knowledge_map_overview: Parágrafo de visão geral do mapa de conhecimento.
            topic_sequence: Lista de tópicos em ordem (como texto).
            structured_concepts: JSON dos conceitos da aula (como string).
            student_clarity_score: Nota de clareza 0–3.
            student_clarity_justification: Justificativa da nota de clareza.

        Returns:
            str com o resumo em HTML do Telegram (usa <b>, <i>, <code>).
        """

    # ------------------------------------------------------------------
    # P5 — Banco de Perguntas
    # ------------------------------------------------------------------

    @abstractmethod
    async def generate_question_bank(
        self,
        subject: str,
        lesson_number: int,
        student_mastery_summary: str,
        structured_concepts: str,
        knowledge_map: str,
    ) -> dict[str, Any]:
        """Gera banco de 6–10 perguntas de revisão para a aula.

        Args:
            subject: Nome da matéria.
            lesson_number: Número sequencial da aula.
            student_mastery_summary: Resumo textual do domínio do aluno em
                conceitos anteriores.
            structured_concepts: JSON dos conceitos desta aula (como string).
            knowledge_map: JSON do mapa completo da disciplina (como string).

        Returns:
            dict com a chave:
                questions (list[dict]) — cada dict com:
                    id, type, concept_target, difficulty,
                    question_text, context_setup,
                    expected_answer_criteria (list[str]),
                    common_wrong_answers (list[str]),
                    follow_up_if_wrong (str),
                    connects_to_prior_lesson (str | None)
        """

    # ------------------------------------------------------------------
    # P6 — Avaliação de Resposta em Áudio
    # ------------------------------------------------------------------

    @abstractmethod
    async def evaluate_audio_answer_v2(
        self,
        audio_path: Path,
        question_type: str,
        question_text: str,
        expected_answer_criteria: str,
        concept_context: str,
        student_error_history: str,
    ) -> dict[str, Any]:
        """Avalia a resposta oral do aluno a uma pergunta de revisão.

        Args:
            audio_path: Caminho para o arquivo de áudio com a resposta.
            question_type: Tipo da pergunta (ex.: "compreensão", "aplicação").
            question_text: Texto completo da pergunta feita.
            expected_answer_criteria: Lista de critérios (como texto/JSON).
            concept_context: Definição e contexto do conceito avaliado.
            student_error_history: Histórico de erros do aluno neste conceito.

        Returns:
            dict com as chaves:
                transcript_of_answer (str),
                criteria_evaluation (list[dict]),
                overall_score (int 0-3),
                score_justification (str),
                what_student_got_right (list[str]),
                what_student_got_wrong (list[str]),
                what_student_missed (list[str]),
                is_recurring_error (bool),
                recurring_error_detail (str | None),
                feedback_to_student (str),
                suggested_next_action (str)
        """

    # ------------------------------------------------------------------
    # P7 — Decisão Pedagógica
    # ------------------------------------------------------------------

    @abstractmethod
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
        """Decide o próximo passo da sessão de revisão.

        Args:
            evaluation: JSON da avaliação P6 (como string).
            question_type: Tipo da pergunta que foi feita.
            question_difficulty: Dificuldade da pergunta ("fácil"|"médio"|"difícil").
            question_asked: Texto da pergunta que foi feita.
            session_history: Histórico das interações da sessão atual.
            available_questions: JSON das perguntas disponíveis do banco P5.
            knowledge_map_overview: Parágrafo de visão geral do aprendizado.

        Returns:
            dict com as chaves:
                reasoning (str), action (str), action_justification (str),
                content (dict com message_to_student, explanation_if_needed,
                         example_if_needed, next_question_id, next_question_override),
                session_should_end_after_this (bool),
                end_reason_if_ending (str | None)
        """

    # ------------------------------------------------------------------
    # Métodos legados — mantidos para não quebrar código existente
    # NÃO use em código novo. Use os métodos P1–P7 acima.
    # ------------------------------------------------------------------

    async def process_audio_to_summary(
        self,
        audio_path: Path,
        subject: str,
        prompt: str,
    ) -> str:
        """[LEGADO] Processa áudio + prompt → resumo em texto.

        Deprecated: Use o pipeline P1 → P4 (analyze_audio_multimodal +
        extract_lesson_knowledge + update_knowledge_map +
        generate_pedagogical_summary) para gerar resumos.
        """
        raise NotImplementedError(
            "process_audio_to_summary é legado. "
            "Use analyze_audio_multimodal → extract_lesson_knowledge → "
            "update_knowledge_map → generate_pedagogical_summary."
        )

    async def generate_review_question(self, summary: str) -> str:
        """[LEGADO] Gera pergunta de revisão a partir do resumo.

        Deprecated: Use generate_question_bank (P5) para gerar perguntas.
        """
        raise NotImplementedError(
            "generate_review_question é legado. "
            "Use generate_question_bank (P5) para gerar o banco de perguntas."
        )

    async def evaluate_audio_answer(
        self,
        audio_path: Path,
        summary: str,
        question: str,
    ) -> dict:
        """[LEGADO] Avalia resposta em áudio → {feedback: str, score: int}.

        Deprecated: Use evaluate_audio_answer_v2 (P6) para avaliação completa.
        """
        raise NotImplementedError(
            "evaluate_audio_answer é legado. "
            "Use evaluate_audio_answer_v2 (P6) para avaliação completa."
        )
