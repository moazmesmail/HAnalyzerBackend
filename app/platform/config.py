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
    video_max_duration_seconds: float = 120
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1/chat/completions"
    openrouter_model: str = "qwen/qwen3-vl-32b-instruct"
    openrouter_provider_sort: str = "throughput"
    openrouter_retry_provider_sort: str = "latency"
    openrouter_timeout_seconds: int = 600
    openrouter_max_output_tokens: int = 6000
    openrouter_max_retries: int = 3
    openrouter_retry_max_wait_seconds: float = 10
    analysis_batch_max_attempts: int = 2
    analysis_batch_retry_seconds: float = 2
    analysis_batch_seconds: float = 10
    analysis_batch_concurrency: int = 3
    analysis_batch_launch_interval_seconds: float = 5
    analysis_retry_max_output_tokens: int = 4500
    analysis_max_fps: float = 15
    analysis_contact_sheet_frames: int = 30
    analysis_contact_sheet_cell_width: int = 240
    analysis_contact_sheet_cell_height: int = 135
    analysis_contact_sheet_jpeg_quality: int = 70
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
