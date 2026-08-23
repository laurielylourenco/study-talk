from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str
    database_url: str = "sqlite+aiosqlite:///./data/estudobot.db"
    app_env: str = "development"

    allowed_telegram_ids: list[int] = []

    llm_provider: str = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"

    # Modelos especializados por papel (free tier Google AI Studio)
    gemini_model_multimodal: str = "gemini-3.5-flash-lite"  # P1, P6 — 500 RPD
    gemini_model_text_fast: str = "gemini-3.1-flash-lite"  # P2, P3 — 500 RPD
    gemini_model_summary: str = "gemini-3.5-flash-lite"  # P4 — 500 RPD
    gemini_model_questions: str = "gemini-3.7-flash"  # P5 — 20 RPD
    gemini_model_reasoning: str = "gemini-3.5-flash"  # P7 — 20 RPD

    @field_validator("allowed_telegram_ids", mode="before")
    @classmethod
    def parse_allowed_ids(cls, value: object) -> list[int]:
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return [int(v) for v in value]
        if isinstance(value, int):
            return [value]
        if isinstance(value, str):
            parts = [p.strip() for p in value.split(",") if p.strip()]
            return [int(p) for p in parts]
        raise TypeError(f"allowed_telegram_ids inválido: {value!r}")

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in {"production", "prod"}

    @property
    def env_badge(self) -> str:
        return "prod" if self.is_production else "dev"


settings = Settings()
