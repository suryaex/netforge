"""Application configuration loaded from environment variables.

Mirrors the secureops/storagehub settings style (pydantic-settings + a cached
``settings`` singleton) so the three projects share a baseline. NetForge adds
Redis (realtime state / job queue) and engine knobs.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # App
    APP_NAME: str = "NetForge"
    APP_VERSION: str = "0.1"
    ENVIRONMENT: str = "development"
    SECRET_KEY: str = "change-me"
    CORS_ORIGINS: str = "http://localhost,http://localhost:5173,http://localhost:3000"

    # URLs
    FRONTEND_URL: str = "http://localhost:5173"
    BACKEND_URL: str = "http://localhost:8000"
    API_V1_PREFIX: str = "/api"

    # Database (PostgreSQL per MASTER_SPEC §2; async driver)
    DATABASE_URL: str = "postgresql+asyncpg://netforge:netforge@localhost:5432/netforge"

    # Redis — realtime state, pub/sub for WS fan-out, job queue
    REDIS_URL: str = "redis://localhost:6379/0"

    # Simulation engine
    SIM_MAX_NODES: int = 5000          # soft guard for a single in-process run
    SIM_DEFAULT_SEED: int = 0
    SIM_MAX_EVENTS: int = 5_000_000    # runaway guard
    SIM_METRIC_INTERVAL: float = 1.0

    # Emulation backend: "null" | "containerlab" | "docker"
    EMULATION_BACKEND: str = "null"

    # Security headers
    ENABLE_HSTS: bool = False

    # In-app self-update (see app/services/updater.py + scripts/self-update.sh).
    # GITHUB_REPO is the "owner/name" slug whose releases we compare against.
    GITHUB_REPO: str = "suryaex/netforge"
    UPDATE_BRANCH: str = "main"
    # Shared secret required to call POST /api/update/apply (NetForge has no auth
    # layer yet). Leave blank to DISABLE applying updates from the app.
    UPDATE_TOKEN: str = ""
    # Sentinel + status files exchanged with the host-side scripts/self-update.sh.
    UPDATE_TRIGGER_FILE: str = "/var/lib/netforge/update.request"
    UPDATE_STATUS_FILE: str = "/var/lib/netforge/update.status"
    # When "1" the backend may run scripts/self-update.sh itself (needs the repo +
    # docker socket mounted). Otherwise it only drops the trigger file for a
    # host-side watcher to pick up — the safer default in containers.
    UPDATE_INPROC: bool = False

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @field_validator("ENABLE_HSTS", "UPDATE_INPROC", mode="before")
    @classmethod
    def _parse_bool(cls, v):  # noqa: ANN001
        if isinstance(v, str):
            return v.strip().lower() in {"1", "true", "yes", "on"}
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
