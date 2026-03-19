"""
NovaSRE Configuration — Pydantic Settings v2
All configuration is loaded from environment variables / .env file.
"""
from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # === LLM ===
    openai_api_key: str = Field(default="", description="OpenAI API key")
    openai_model_primary: str = Field(default="gpt-4o", description="Primary LLM model")
    openai_model_fast: str = Field(default="gpt-4o-mini", description="Fast LLM model")
    openai_embedding_model: str = Field(
        default="text-embedding-3-large", description="Embedding model"
    )

    # === Database ===
    database_url: str = Field(
        default="postgresql+asyncpg://novasre:secret@localhost:5432/novasre",
        description="Async PostgreSQL connection URL",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0", description="Redis connection URL"
    )

    # === Grafana Enterprise ===
    grafana_url: str = Field(
        default="https://grafana.your-org.com", description="Grafana base URL"
    )
    grafana_api_key: str = Field(default="", description="Grafana API key")
    grafana_org_id: int = Field(default=1, description="Grafana org ID")

    # === Mimir (Prometheus-compatible) ===
    mimir_url: str = Field(
        default="https://mimir.your-org.com", description="Mimir base URL"
    )
    mimir_tenant_id: str = Field(default="your-tenant", description="Mimir tenant ID")
    mimir_basic_auth_user: str = Field(default="", description="Mimir basic auth user")
    mimir_basic_auth_password: str = Field(
        default="", description="Mimir basic auth password"
    )

    # === Loki ===
    loki_url: str = Field(
        default="https://loki.your-org.com", description="Loki base URL"
    )
    loki_tenant_id: str = Field(default="your-tenant", description="Loki tenant ID")

    # === Tempo ===
    tempo_url: str = Field(
        default="https://tempo.your-org.com", description="Tempo base URL"
    )
    tempo_tenant_id: str = Field(default="your-tenant", description="Tempo tenant ID")

    # === Pyroscope ===
    pyroscope_url: str = Field(
        default="https://pyroscope.your-org.com", description="Pyroscope base URL"
    )
    pyroscope_api_key: str = Field(default="", description="Pyroscope API key")

    # === Faro (Grafana Frontend Observability) ===
    faro_collector_url: str = Field(
        default="https://faro-collector.your-org.com",
        description="Faro collector URL",
    )
    faro_api_key: str = Field(default="", description="Faro API key")

    # === MCP Server ===
    mcp_server_url: str = Field(
        default="http://localhost:8001", description="MCP server URL"
    )
    mcp_server_api_key: str = Field(default="", description="MCP server API key")

    # === Alertmanager ===
    alertmanager_url: str = Field(
        default="https://alertmanager.your-org.com",
        description="Alertmanager base URL",
    )

    # === Vector Store (ChromaDB) ===
    chroma_host: str = Field(default="localhost", description="ChromaDB host")
    chroma_port: int = Field(default=8002, description="ChromaDB port")
    chroma_collection_incidents: str = Field(
        default="novasre_incidents", description="Incidents ChromaDB collection"
    )
    chroma_collection_runbooks: str = Field(
        default="novasre_runbooks", description="Runbooks ChromaDB collection"
    )

    # === App Config ===
    app_env: str = Field(default="development", description="Application environment")
    app_secret_key: str = Field(
        default="change-me-in-production", description="Application secret key"
    )
    cors_origins: str = Field(
        default="http://localhost:3000,http://localhost:5173",
        description="Comma-separated list of allowed CORS origins",
    )
    log_level: str = Field(default="INFO", description="Log level")

    # === Alert Correlation ===
    correlation_temporal_window_seconds: int = Field(
        default=300, description="Temporal correlation window in seconds"
    )
    correlation_semantic_threshold: float = Field(
        default=0.75, description="Semantic similarity threshold for correlation"
    )
    correlation_topological_depth: int = Field(
        default=3, description="Topological correlation depth (BFS hops)"
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str) -> str:
        # Allow comma-separated or list
        if isinstance(v, list):
            return ",".join(v)
        return v

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


@lru_cache
def get_settings() -> Settings:
    """Return cached Settings instance."""
    return Settings()


# Module-level singleton for convenience
settings = get_settings()
