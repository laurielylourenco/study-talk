from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str
    database_url: str = "sqlite+aiosqlite:///./data/estudobot.db"

    # Meta 2+ (carregados mas não usados na Meta 1)
    llm_provider: str = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"


settings = Settings()
