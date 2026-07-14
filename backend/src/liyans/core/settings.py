from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LIYAN_",
        env_file=".env",
        extra="ignore",
    )

    environment: str = "development"
    database_url: str = "postgresql+asyncpg://liyans:liyans@localhost:5432/liyans"
    artifact_root: Path = REPOSITORY_ROOT / "var" / "artifacts"
    audit_log_path: Path = REPOSITORY_ROOT / "var" / "audit" / "events.jsonl"
    provider_policy_path: Path = REPOSITORY_ROOT / "config" / "providers.toml"
    provider_policy_poll_seconds: float = 2.0
    task_worker_count: int = 4
    sse_replay_capacity: int = 4096
    sse_subscriber_queue_size: int = 128
    sse_cursor_secret: str = Field(default_factory=lambda: secrets.token_hex(32), repr=False)

    @model_validator(mode="after")
    def validate_environment(self) -> Settings:
        if self.environment == "production" and not os.getenv("LIYAN_SSE_CURSOR_SECRET"):
            raise ValueError("production requires LIYAN_SSE_CURSOR_SECRET")
        if len(self.sse_cursor_secret.encode("utf-8")) < 32:
            raise ValueError("sse_cursor_secret must contain at least 32 bytes")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
