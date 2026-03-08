from pathlib import Path
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.runtime import get_app_root


ROOT_DIR = get_app_root()
ENV_FILE = ROOT_DIR / ".env"
DEFAULT_CORS_ORIGINS = [
    "http://127.0.0.1:3000",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    APP_NAME: str = "AutoChatGPT Manager"
    APP_VERSION: str = "1.1.0"
    DEBUG: bool = False
    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = 8000

    DATABASE_URL: str = f"sqlite:///{(ROOT_DIR / 'data' / 'auto_chatgpt.db').as_posix()}"

    SECRET_KEY: str = "change-this-secret-key-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7

    DOMAIN_NAME: str = ""
    CF_API_TOKEN: Optional[str] = None
    CF_ZONE_ID: Optional[str] = None
    CF_ACCOUNT_ID: Optional[str] = None
    CF_EMAIL_FORWARD_TO: Optional[str] = None

    IMAP_HOST: str = "imap.gmail.com"
    IMAP_PORT: int = 993
    IMAP_USER: str = ""
    IMAP_PASSWORD: str = ""

    PROXY_HOST: Optional[str] = None
    PROXY_PORT: Optional[int] = None
    PROXY_USER: Optional[str] = None
    PROXY_PASS: Optional[str] = None

    OPENAI_API_BASE: str = "https://api.openai.com"
    CORS_ORIGINS: str = ",".join(DEFAULT_CORS_ORIGINS)

    REGISTRATION_TIMEOUT: int = 120

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug_value(cls, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on", "debug", "dev", "development"}:
                return True
            if normalized in {"0", "false", "no", "off", "release", "prod", "production"}:
                return False
        return value

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        return (
            init_settings,
            dotenv_settings,
            env_settings,
            file_secret_settings,
        )

    @property
    def cors_origins_list(self) -> list[str]:
        origins = [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]
        return origins or list(DEFAULT_CORS_ORIGINS)

    @property
    def public_base_url(self) -> str:
        return f"http://{self.APP_HOST}:{self.APP_PORT}"

    @property
    def codex_proxy_url(self) -> str:
        return f"{self.public_base_url}/v1"


settings = Settings()
