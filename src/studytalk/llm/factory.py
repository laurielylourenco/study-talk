from studytalk.config import Settings
from studytalk.llm.base import LLMProvider
from studytalk.llm.gemini_provider import GeminiProvider


def get_llm_provider(config: Settings | None = None) -> LLMProvider:
    """Instancia e retorna o provedor de LLM configurado.

    Lê ``LLM_PROVIDER`` (padrão: "gemini") e instancia o provedor
    correspondente com todos os modelos por tarefa definidos em ``Settings``.

    Args:
        config: Instância de ``Settings`` a usar. Se ``None``, usa o
            singleton ``settings`` importado de ``studytalk.config``.

    Returns:
        Instância concreta de ``LLMProvider``.

    Raises:
        ValueError: Se ``LLM_PROVIDER`` tiver valor desconhecido.
    """
    from studytalk.config import settings as default_settings

    cfg = config or default_settings
    provider = (cfg.llm_provider or "gemini").lower().strip()

    if provider == "gemini":
        return GeminiProvider(
            api_key=cfg.gemini_api_key,
            model=cfg.gemini_model,
            model_multimodal=cfg.gemini_model_multimodal,
            model_text_fast=cfg.gemini_model_text_fast,
            model_summary=cfg.gemini_model_summary,
            model_questions=cfg.gemini_model_questions,
            model_reasoning=cfg.gemini_model_reasoning,
        )

    raise ValueError(
        f"Provedor desconhecido: {cfg.llm_provider!r}. "
        "Use LLM_PROVIDER=gemini."
    )
