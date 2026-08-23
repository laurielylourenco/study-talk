"""Utilitários para parsear respostas JSON de LLMs."""

from __future__ import annotations

import json
import re
from typing import Any


class LLMParsingError(Exception):
    """Levantada quando a resposta do LLM não pode ser convertida em JSON válido."""

    def __init__(
        self,
        message: str,
        raw_response: str = "",
        missing_fields: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.raw_response = raw_response
        self.missing_fields = missing_fields or []

    def __repr__(self) -> str:
        snippet = self.raw_response[:200].replace("\n", " ")
        return (
            f"LLMParsingError({self.args[0]!r}, "
            f"missing_fields={self.missing_fields!r}, "
            f"raw_snippet={snippet!r})"
        )


def parse_llm_json(
    raw: str,
    required_fields: list[str] | None = None,
    context: str = "",
) -> dict[str, Any]:
    """Converte a resposta de texto do LLM em dict Python.

    Etapas:
    1. Remove delimitadores de code fence (json) se presentes.
    2. Tenta ``json.loads`` diretamente.
    3. Se falhar, tenta extrair o primeiro bloco JSON via regex.
    4. Valida que o resultado é um dict e que todos os ``required_fields`` estão presentes.
    5. Levanta ``LLMParsingError`` com contexto útil em qualquer falha.

    Args:
        raw: String bruta retornada pelo LLM.
        required_fields: Lista de chaves que devem existir no JSON retornado.
            Se ``None`` ou lista vazia, nenhuma validação de campos é feita.
        context: Rótulo descritivo exibido nas mensagens de erro
            (ex.: "P1-analyze_audio_multimodal").

    Returns:
        dict com o JSON parseado.

    Raises:
        LLMParsingError: Se o JSON não puder ser extraído ou campos obrigatórios
            estiverem ausentes.
    """
    ctx_suffix = f" ({context})" if context else ""

    if not raw or not raw.strip():
        raise LLMParsingError(
            f"Resposta vazia do LLM{ctx_suffix}",
            raw_response=raw or "",
        )

    # Etapa 1 — remover code fences
    cleaned = raw.strip()
    fence_match = re.match(
        r"^```(?:json)?\s*\n?([\s\S]*?)\n?```\s*$",
        cleaned,
        re.DOTALL,
    )
    if fence_match:
        cleaned = fence_match.group(1).strip()

    # Etapa 2 — tentativa direta
    data: dict[str, Any] | None = None
    last_error: Exception | None = None

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        last_error = exc

    # Etapa 3 — extração via regex (pega o primeiro objeto JSON da string)
    if data is None:
        json_match = re.search(r"\{[\s\S]*\}", raw, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                last_error = None
            except json.JSONDecodeError as exc:
                last_error = exc

    if data is None:
        raise LLMParsingError(
            f"Não foi possível parsear JSON do LLM{ctx_suffix}: {last_error}",
            raw_response=raw,
        )

    # Etapa 4a — garantir que é dict
    if not isinstance(data, dict):
        raise LLMParsingError(
            f"JSON do LLM não é um objeto{ctx_suffix}: tipo={type(data).__name__}",
            raw_response=raw,
        )

    # Etapa 4b — validar campos obrigatórios
    if required_fields:
        missing = [f for f in required_fields if f not in data]
        if missing:
            raise LLMParsingError(
                f"JSON do LLM está faltando campos obrigatórios{ctx_suffix}: {missing}",
                raw_response=raw,
                missing_fields=missing,
            )

    return data
