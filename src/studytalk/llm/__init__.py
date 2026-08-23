"""Pacote LLM do study-talk.

Símbolos públicos principais:
  LLMProvider      — classe base abstrata (define a interface dos 7 métodos P1–P7)
  GeminiProvider   — implementação concreta via Google Gemini (multi-modelo)
  get_llm_provider — factory que retorna o provedor configurado via Settings
  LLMParsingError  — exceção levantada quando a resposta JSON do LLM é inválida
  parse_llm_json   — utilitário para parsear e validar respostas JSON do LLM
"""

from studytalk.llm.base import LLMProvider
from studytalk.llm.factory import get_llm_provider
from studytalk.llm.gemini_provider import GeminiProvider
from studytalk.llm.parsing import LLMParsingError, parse_llm_json

__all__ = [
    "GeminiProvider",
    "LLMParsingError",
    "LLMProvider",
    "get_llm_provider",
    "parse_llm_json",
]
