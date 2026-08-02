from abc import ABC, abstractmethod
from pathlib import Path


class LLMProvider(ABC):
    @abstractmethod
    async def process_audio_to_summary(
        self,
        audio_path: Path,
        subject: str,
        prompt: str,
    ) -> str:
        """Processa áudio + prompt → resumo em texto."""

    @abstractmethod
    async def generate_review_question(self, summary: str) -> str:
        """Gera pergunta de revisão a partir do resumo (Meta 4)."""

    @abstractmethod
    async def evaluate_audio_answer(
        self,
        audio_path: Path,
        summary: str,
        question: str,
    ) -> dict:
        """Avalia resposta em áudio → {feedback: str, score: int} (Meta 4)."""
