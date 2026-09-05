from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "Competition Analysis"
    api_prefix: str = "/api/v1"
    app_origin: str = "http://127.0.0.1:5173"
    database_url: str = "postgresql+psycopg://competition:competition@localhost:5432/competition_analysis"
    storage_root: Path = Path("../storage")
    session_cookie_name: str = "__Host-session"
    dev_session_cookie_name: str = "dev-session"
    secure_cookies: bool = False
    session_absolute_minutes: int = 8 * 60
    upload_max_bytes: int = 1024 * 1024 * 1024
    csrf_secret: str = Field(default="change-me-in-production", min_length=12)
    auth_rate_limit_window_seconds: int = 300
    auth_rate_limit_attempts: int = 10

    @property
    def allowed_origins(self) -> list[str]:
        origins = {
            self.app_origin,
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        }
        return sorted(origins)

    def is_allowed_origin(self, origin: str) -> bool:
        if origin in self.allowed_origins:
            return True

        parsed = urlparse(origin)
        if parsed.scheme != "http":
            return False

        return parsed.hostname in {"127.0.0.1", "localhost"} and parsed.port in range(5173, 5184)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    return settings
