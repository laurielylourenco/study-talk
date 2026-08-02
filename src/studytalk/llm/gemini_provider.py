import asyncio
import logging
from pathlib import Path

from google import genai
from google.genai import types

from studytalk.llm.base import LLMProvider
from studytalk.llm.prompts import EVALUATE_ANSWER_PROMPT, REVIEW_QUESTION_PROMPT

logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-flash-latest") -> None:
        if not api_key:
            raise ValueError("GEMINI_API_KEY não configurada")
        self._client = genai.Client(api_key=api_key)
        self._model = model

    def _mime_for(self, audio_path: Path) -> str:
        suffix = audio_path.suffix.lower()
        return {
            ".ogg": "audio/ogg",
            ".oga": "audio/ogg",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".m4a": "audio/mp4",
            ".webm": "audio/webm",
        }.get(suffix, "audio/ogg")

    def _generate_with_audio(self, prompt: str, audio_path: Path) -> str:
        mime = self._mime_for(audio_path)
        uploaded = self._client.files.upload(
            file=str(audio_path),
            config=types.UploadFileConfig(mime_type=mime),
        )
        response = self._client.models.generate_content(
            model=self._model,
            contents=[prompt, uploaded],
        )
        text = (response.text or "").strip()
        if not text:
            raise RuntimeError("Gemini retornou resposta vazia")
        return text

    def _generate_text(self, prompt: str) -> str:
        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
        )
        text = (response.text or "").strip()
        if not text:
            raise RuntimeError("Gemini retornou resposta vazia")
        return text

    async def process_audio_to_summary(
        self,
        audio_path: Path,
        subject: str,
        prompt: str,
    ) -> str:
        return await asyncio.to_thread(self._generate_with_audio, prompt, audio_path)

    async def generate_review_question(self, summary: str) -> str:
        prompt = REVIEW_QUESTION_PROMPT.format(summary=summary)
        return await asyncio.to_thread(self._generate_text, prompt)

    async def evaluate_audio_answer(
        self,
        audio_path: Path,
        summary: str,
        question: str,
    ) -> dict:
        prompt = EVALUATE_ANSWER_PROMPT.format(summary=summary, question=question)
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
