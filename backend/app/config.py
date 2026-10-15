"""Application settings, loaded from environment / .env. Secrets never live in code."""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://claims:claims@localhost:5432/claims"
    confidence_threshold: int = 80

    ai_provider: str = "rule_based"  # rule_based | anthropic | openai
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 30

    cors_origins: str = "http://localhost:5173"

    upload_dir: str = "uploads"
    max_upload_mb: int = 5

    # Load docs/samples/sample_claims.json on startup when the claims table is empty (demo deploys).
    seed_sample_claims: bool = False

    @field_validator("database_url")
    @classmethod
    def _use_psycopg3(cls, v: str) -> str:
        """Hosting providers (e.g. Render) give postgres:// or postgresql:// URLs; SQLAlchemy needs the driver."""
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        # A bare hostname (as Render's Blueprint provides) is treated as https.
        origins = [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]
        return [o if "://" in o else f"https://{o}" for o in origins]


@lru_cache
def get_settings() -> Settings:
    return Settings()
