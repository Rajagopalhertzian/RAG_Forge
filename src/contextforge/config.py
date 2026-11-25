"""
ContextForge Configuration Module

Uses Pydantic Settings v2 for environment-driven configuration.
All settings are loaded from environment variables with sensible defaults.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import (
    AnyHttpUrl,
    BeforeValidator,
    Field,
    PostgresDsn,
    RedisDsn,
    ValidationInfo,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


def parse_cors(v: str | list[str]) -> list[str]:
    """Parse CORS origins from string or list."""
    if isinstance(v, str):
        return [origin.strip() for origin in v.split(",")]
    return v


def parse_list(v: str | list[str]) -> list[str]:
    """Parse comma-separated string to list."""
    if isinstance(v, str):
        return [item.strip() for item in v.split(",")]
    return v


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
        validate_default=True,
    )

    # =========================================================================
    # Application
    # =========================================================================
    APP_NAME: str = "contextforge"
    APP_ENV: Literal["development", "staging", "production", "testing"] = "development"
    APP_DEBUG: bool = True
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    APP_WORKERS: int = 4

    # =========================================================================
    # Database (PostgreSQL + pgvector)
    # =========================================================================
    DATABASE_URL: PostgresDsn
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10
    DATABASE_POOL_TIMEOUT: int = 30
    DATABASE_ECHO: bool = False

    @computed_field
    @property
    def database_url_sync(self) -> str:
        """Sync version of database URL for Alembic."""
        return str(self.DATABASE_URL).replace("postgresql+asyncpg://", "postgresql://")

    # =========================================================================
    # Redis
    # =========================================================================
    REDIS_URL: RedisDsn
    REDIS_MAX_CONNECTIONS: int = 50
    REDIS_SOCKET_TIMEOUT: int = 5
    REDIS_SOCKET_CONNECT_TIMEOUT: int = 5

    # =========================================================================
    # Celery
    # =========================================================================
    CELERY_BROKER_URL: RedisDsn
    CELERY_RESULT_BACKEND: RedisDsn
    CELERY_TASK_SERIALIZER: str = "json"
    CELERY_RESULT_SERIALIZER: str = "json"
    CELERY_ACCEPT_CONTENT: Annotated[list[str], BeforeValidator(parse_list)] = ["json"]
    CELERY_TIMEZONE: str = "UTC"
    CELERY_TASK_TRACK_STARTED: bool = True
    CELERY_TASK_TIME_LIMIT: int = 3600
    CELERY_WORKER_PREFETCH_MULTIPLIER: int = 4
    CELERY_WORKER_MAX_TASKS_PER_CHILD: int = 1000

    # =========================================================================
    # Vector Stores
    # =========================================================================
    VECTOR_STORE: Literal["pgvector", "faiss", "weaviate"] = "pgvector"

    # pgvector HNSW settings
    PGVECTOR_HNSW_M: int = 16
    PGVECTOR_HNSW_EF_CONSTRUCTION: int = 64
    PGVECTOR_HNSW_EF_SEARCH: int = 40

    # FAISS settings
    FAISS_INDEX_PATH: str = "./data/faiss_index"
    FAISS_INDEX_TYPE: str = "HNSW32"

    # Weaviate settings
    WEAVIATE_URL: AnyHttpUrl = "http://localhost:8080"
    WEAVIATE_API_KEY: str | None = None
    WEAVIATE_CLASS_PREFIX: str = "ContextForge"

    # =========================================================================
    # Embedding Providers
    # =========================================================================
    # OpenAI / Azure OpenAI
    OPENAI_API_KEY: str | None = None
    OPENAI_ORGANIZATION: str | None = None
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-large"
    OPENAI_EMBEDDING_DIMENSIONS: int = 3072
    OPENAI_API_VERSION: str = "2024-02-15-preview"
    AZURE_OPENAI_ENDPOINT: str | None = None
    AZURE_OPENAI_API_KEY: str | None = None
    AZURE_OPENAI_DEPLOYMENT_NAME: str | None = None

    # Anthropic (for synthesis)
    ANTHROPIC_API_KEY: str | None = None

    # AWS Bedrock
    AWS_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None
    BEDROCK_EMBEDDING_MODEL: str = "amazon.titan-embed-text-v2:0"
    BEDROCK_EMBEDDING_DIMENSIONS: int = 1024

    # Local (sentence-transformers)
    LOCAL_EMBEDDING_MODEL: str = "BAAI/bge-m3"
    LOCAL_EMBEDDING_DIMENSIONS: int = 1024
    LOCAL_EMBEDDING_DEVICE: Literal["cpu", "cuda", "mps"] = "cpu"
    LOCAL_EMBEDDING_BATCH_SIZE: int = 32

    # =========================================================================
    # Chunking Configuration
    # =========================================================================
    DEFAULT_CHUNK_STRATEGY: Literal["semantic", "hierarchical", "code", "fixed"] = "semantic"
    DEFAULT_CHUNK_SIZE: int = 512
    DEFAULT_CHUNK_OVERLAP: int = 50
    SEMANTIC_CHUNK_THRESHOLD: float = 0.7
    HIERARCHICAL_PARENT_SIZE: int = 1024
    HIERARCHICAL_CHILD_SIZE: int = 256
    CODE_CHUNK_MAX_LINES: int = 100
    FIXED_CHUNK_SEPARATORS: Annotated[list[str], BeforeValidator(parse_list)] = [
        "\n\n", "\n", ". ", " ", ""
    ]

    # =========================================================================
    # Rate Limiting (Token Bucket)
    # =========================================================================
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 60
    RATE_LIMIT_BURST: int = 10
    RATE_LIMIT_REDIS_KEY_PREFIX: str = "ratelimit:"

    # =========================================================================
    # Observability
    # =========================================================================
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    LOG_FORMAT: Literal["json", "console"] = "json"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"
    OTEL_SERVICE_NAME: str = "contextforge"
    OTEL_SAMPLER: str = "always_on"
    PROMETHEUS_METRICS_PORT: int = 9090

    # =========================================================================
    # Security
    # =========================================================================
    SECRET_KEY: str = Field(
        default_factory=lambda: secrets.token_urlsafe(32),
        min_length=32,
    )
    API_KEY_HEADER: str = "X-API-Key"
    CORS_ORIGINS: Annotated[list[str], BeforeValidator(parse_cors)] = [
        "http://localhost:3000",
        "http://localhost:8080",
    ]
    CORS_ALLOW_CREDENTIALS: bool = True

    # =========================================================================
    # Ingestion
    # =========================================================================
    INGESTION_MAX_FILE_SIZE_MB: int = 100
    INGESTION_MAX_CONCURRENT_JOBS: int = 4
    INGESTION_CHUNK_BATCH_SIZE: int = 100
    INGESTION_EMBEDDING_BATCH_SIZE: int = 32
    INGESTION_RETRY_ATTEMPTS: int = 3
    INGESTION_RETRY_BACKOFF: float = 2.0

    # Source-specific
    NOTION_API_KEY: str | None = None
    NOTION_API_VERSION: str = "2022-06-28"
    CONFLUENCE_URL: str | None = None
    CONFLUENCE_USERNAME: str | None = None
    CONFLUENCE_API_TOKEN: str | None = None
    GITHUB_TOKEN: str | None = None
    GITHUB_ORG: str | None = None
    SLACK_BOT_TOKEN: str | None = None
    SLACK_APP_TOKEN: str | None = None

    # =========================================================================
    # MCP Gateway
    # =========================================================================
    MCP_SERVER_HOST: str = "0.0.0.0"
    MCP_SERVER_PORT: int = 8001
    MCP_AUTH_ENABLED: bool = True
    MCP_ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:8080"]
    MCP_REDIRECT_URI: str = "http://localhost:8001/callback"

    # OAuth Providers
    COGNITO_USER_POOL_ID: str | None = None
    COGNITO_CLIENT_ID: str | None = None
    COGNITO_CLIENT_SECRET: str | None = None
    CLERK_ISSUER_URL: str | None = None
    CLERK_CLIENT_ID: str | None = None
    CLERK_CLIENT_SECRET: str | None = None

    # =========================================================================
    # Validation
    # =========================================================================
    @field_validator("SECRET_KEY", mode="before")
    @classmethod
    def validate_secret_key(cls, v: str | None, info: ValidationInfo) -> str:
        if v is None or v == "your-secret-key-change-in-production-min-32-chars":
            app_env = info.data.get("APP_ENV", "development")
            if app_env == "production":
                raise ValueError("SECRET_KEY must be set in production")
            return secrets.token_urlsafe(32)
        return v

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v:
            raise ValueError("DATABASE_URL must be set")
        return v

    @field_validator("REDIS_URL", mode="before")
    @classmethod
    def validate_redis_url(cls, v: str) -> str:
        if not v:
            raise ValueError("REDIS_URL must be set")
        return v

    @model_validator(mode="after")
    def validate_embedding_config(self) -> Settings:
        """Validate that at least one embedding provider is configured."""
        providers = 0
        if self.OPENAI_API_KEY or self.AZURE_OPENAI_API_KEY:
            providers += 1
        if self.AWS_ACCESS_KEY_ID and self.AWS_SECRET_ACCESS_KEY:
            providers += 1
        # Local is always available
        providers += 1

        if providers == 0:
            raise ValueError("At least one embedding provider must be configured")
        return self

    @property
    def is_development(self) -> bool:
        return self.APP_ENV == "development"

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Export commonly used settings
settings = get_settings()
