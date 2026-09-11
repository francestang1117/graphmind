"""Runtime settings loaded from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_SECRET_KEY = "dev-only-change-me-before-deploy"
LOCAL_ENVIRONMENTS = {"development", "test"}
KNOWN_ENVIRONMENTS = {
    "development",
    "test",
    "staging",
    "production",
}


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
    # Filled by CI/Docker when available. Local runs can leave it blank.
    GIT_SHA: str = ""
    DEBUG: bool = False
    ENVIRONMENT: str = "development"
    API_V1_PREFIX: str = "/api/v1"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    REFRESH_COOKIE_NAME: str = "graphmind_refresh"
    REFRESH_COOKIE_SECURE: bool = False
    REFRESH_COOKIE_SAMESITE: str = "lax"
    BCRYPT_ROUNDS: int = 12
    REDIS_URL: str = "redis://localhost:6379/0"
    # Only enable this in a single-process local setup. Production needs Redis
    # because the API and WebSocket connection may land on different workers.
    WEBSOCKET_TICKET_MEMORY_FALLBACK: bool = False
    AUTH_REQUIRED: bool = True
    GITHUB_OAUTH_CLIENT_ID: str = ""
    GITHUB_OAUTH_CLIENT_SECRET: str = ""
    GITHUB_OAUTH_CALLBACK_URL: str = "http://localhost:8000/api/v1/auth/github/callback"
    DATABASE_URL: str = "sqlite:///./graphmind.db"
    CELERY_BROKER_URL: str = "memory://"
    CELERY_RESULT_BACKEND: str = "cache+memory://"
    # Local uploads still use FastAPI background tasks unless this is enabled.
    CELERY_ENABLED: bool = False
    # Off by default: reindexing is handy, surprise background work is not.
    CELERY_REINDEX_ENABLED: bool = False
    CELERY_REINDEX_INTERVAL_SECONDS: int = 86400
    CELERY_TASK_DEFAULT_QUEUE: str = "documents"
    CELERY_JOB_CLEANUP_ENABLED: bool = False
    CELERY_JOB_CLEANUP_INTERVAL_SECONDS: int = 86400
    JOB_HISTORY_RETENTION_DAYS: int = 30

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
    RATE_LIMIT_LITERATURE: str = "10/hour;50/day"
    TRUSTED_PROXY_IPS: List[str] = ["127.0.0.1", "::1"]

    METRICS_ENABLED: bool = True
    SENTRY_ENABLED: bool = False
    SENTRY_DSN: str = ""
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0

    # Keep extractive mode as the local default. OpenAI is enabled explicitly
    # after the deployment has reviewed privacy and cost settings.
    MEDICAL_AI_ENABLED: bool = True
    MEDICAL_AI_PROVIDER: str = "extractive"
    MEDICAL_AI_MODEL: str = "extractive-v1"
    MEDICAL_AI_TIMEOUT_SECONDS: int = 30
    MEDICAL_AI_MAX_INPUT_TOKENS: int = 12000
    MEDICAL_AI_MAX_OUTPUT_TOKENS: int = 5000
    MEDICAL_AI_PROVIDER_RETRY_COUNT: int = 2
    MEDICAL_AI_REDACT_PII: bool = True
    # A stale queued or running analysis can be retried after these leases
    # expire. The values are deliberately longer than one normal provider call.
    MEDICAL_AI_QUEUE_LEASE_SECONDS: int = 300
    MEDICAL_AI_RUNNING_LEASE_SECONDS: int = 900
    MEDICAL_AI_PROMPT_VERSION: str = "medical-insights-v2"
    MEDICAL_AI_SCHEMA_VERSION: str = "medical-insights-v2"
    MEDICAL_AI_OPENAI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = ""

    # Literature search sends only confirmed, redacted query terms to PubMed.
    # It never sends the uploaded document itself.
    LITERATURE_SEARCH_ENABLED: bool = True
    PUBMED_BASE_URL: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    PUBMED_API_KEY: str = ""
    PUBMED_TOOL: str = "graphmind"
    PUBMED_EMAIL: str = ""
    PUBMED_TIMEOUT_SECONDS: int = 15
    PUBMED_MAX_RESULTS: int = 50
    PUBMED_CACHE_TTL_SECONDS: int = 86400
    PUBMED_MAX_RESPONSE_BYTES: int = 5242880
    PUBMED_RETRY_COUNT: int = 2
    PUBMED_RATE_LIMIT_ENABLED: bool = True
    PUBMED_RATE_LIMIT_NO_KEY_REQUESTS_PER_SECOND: int = 3
    PUBMED_RATE_LIMIT_WITH_KEY_REQUESTS_PER_SECOND: int = 10
    # Redis is required outside local/test environments so multiple workers
    # cannot each apply an independent PubMed request budget.
    PUBMED_RATE_LIMIT_REDIS_REQUIRED: bool = True

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
    STORAGE_BACKEND: str = "local"
    S3_BUCKET: str = "graphmind"
    S3_ENDPOINT_URL: str = ""
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""
    S3_REGION_NAME: str = "us-east-1"
    S3_PREFIX: str = "uploads"
    S3_FORCE_PATH_STYLE: bool = True

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton avoids re-parsing .env on every call."""
    return Settings()


settings = get_settings()


def validate_runtime_config(config: Settings | None = None) -> None:
    """Reject runtime settings that could silently disable application security."""
    runtime = config or settings
    environment = runtime.ENVIRONMENT.strip().lower()
    secret = runtime.SECRET_KEY.strip()
    problems: list[str] = []

    if environment not in KNOWN_ENVIRONMENTS:
        problems.append(f"ENVIRONMENT has an unsupported value: {environment!r}.")

    is_local = environment in LOCAL_ENVIRONMENTS
    if not is_local and not runtime.AUTH_REQUIRED:
        problems.append("AUTH_REQUIRED must be true outside development and test.")

    if not is_local and runtime.LITERATURE_SEARCH_ENABLED:
        if not runtime.PUBMED_RATE_LIMIT_ENABLED:
            problems.append(
                "PUBMED_RATE_LIMIT_ENABLED must be true outside development and test "
                "when literature search is enabled."
            )
        if not runtime.PUBMED_RATE_LIMIT_REDIS_REQUIRED:
            problems.append(
                "PUBMED_RATE_LIMIT_REDIS_REQUIRED must be true outside development "
                "and test when literature search is enabled."
            )

    if runtime.AUTH_REQUIRED or not is_local:
        if not secret:
            problems.append("SECRET_KEY must not be empty.")
        elif secret == DEFAULT_SECRET_KEY:
            problems.append(
                "SECRET_KEY must not use the public development placeholder."
            )
        elif len(secret) < 32:
            problems.append("SECRET_KEY must contain at least 32 characters.")

    if problems:
        raise RuntimeError(
            "Refusing to start with unsafe runtime configuration:\n- "
            + "\n- ".join(problems)
        )
