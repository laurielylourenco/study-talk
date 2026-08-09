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
    app_env: str = "development"  # development | production

    # Lista de telegram_id permitidos (vírgula). Vazio = libera todos (só local/dev).
    allowed_telegram_ids: list[int] = []

    llm_provider: str = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"

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
