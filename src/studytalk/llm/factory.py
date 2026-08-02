from studytalk.config import Settings
from studytalk.llm.base import LLMProvider
from studytalk.llm.gemini_provider import GeminiProvider


def get_llm_provider(config: Settings | None = None) -> LLMProvider:
    from studytalk.config import settings as default_settings

    cfg = config or default_settings
    provider = (cfg.llm_provider or "gemini").lower().strip()

    if provider == "gemini":
        return GeminiProvider(api_key=cfg.gemini_api_key, model=cfg.gemini_model)

    raise ValueError(
        f"Provedor desconhecido: {cfg.llm_provider!r}. "
        "Use LLM_PROVIDER=gemini (outros provedores na Meta 2+)."
    )
