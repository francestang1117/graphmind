"""Runtime settings loaded from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    APP_NAME: str = "GraphMind"
    APP_VERSION: str = "0.1.0"
    PROJECT_NAME: str = "GraphMind"
    VERSION: str = "0.1.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"
    API_V1_PREFIX: str = "/api/v1"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    SECRET_KEY: str = "dev-only-change-me-before-deploy"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    BCRYPT_ROUNDS: int = 12
    REDIS_URL: str = "redis://localhost:6379/0"
    AUTH_REQUIRED: bool = False
    DATABASE_URL: str = "sqlite:///./graphmind.db"
    CELERY_BROKER_URL: str = "memory://"
    CELERY_RESULT_BACKEND: str = "cache+memory://"
    # Off by default: reindexing is handy, surprise background work is not.
    CELERY_REINDEX_ENABLED: bool = False
    CELERY_REINDEX_INTERVAL_SECONDS: int = 86400

    SPACY_MODEL: str = "en_core_web_sm"
    SPACY_EXTRA_MODELS: List[str] = ["zh_core_web_sm"]

    RATE_LIMIT_ENABLED: bool = True
    # Empty means "use REDIS_URL". This lets production override rate-limit
    # storage separately without changing the rest of the Redis-backed services.
    RATE_LIMIT_STORAGE_URI: str = ""
    RATE_LIMIT_DEFAULT: str = "200/day;50/hour"
    RATE_LIMIT_UPLOAD: str = "10/minute;100/hour"
    RATE_LIMIT_CHAT: str = "30/minute;500/day"
    RATE_LIMIT_SEARCH: str = "60/minute"
    RATE_LIMIT_GRAPH_READ: str = "120/minute"
    RATE_LIMIT_VIDEO: str = "5/hour"
    RATE_LIMIT_SCRAPE: str = "10/hour"
    TRUSTED_PROXY_IPS: List[str] = ["127.0.0.1", "::1"]

    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]

    MAX_UPLOAD_SIZE_MB: int = 50
    # Off locally unless clamd is running.
    VIRUS_SCAN_ENABLED: bool = False
    # Docker/prod should reject uploads when the scanner is down.
    VIRUS_SCAN_FAIL_OPEN: bool = True
    CLAMAV_HOST: str = "localhost"
    CLAMAV_PORT: int = 3310
    CLAMAV_TIMEOUT_SECONDS: int = 30
    ALLOWED_EXTENSIONS: List[str] = [
        ".md", ".pdf", ".txt", ".docx", ".py", ".js", ".ts",
        ".json", ".csv", ".html", ".htm",
    ]
    UPLOAD_DIR: str = str(Path(__file__).resolve().parents[2] / "uploads")

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton avoids re-parsing .env on every call."""
    return Settings()


settings = get_settings()
