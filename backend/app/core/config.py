"""Application configuration loaded from environment variables.

Mirrors the secureops/storagehub settings style (pydantic-settings + a cached
``settings`` singleton) so the three projects share a baseline. NetGeo adds
Redis (realtime state / job queue) and engine knobs.
"""
from __future__ import annotations

import sys
from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # App
    APP_NAME: str = "NetGeo"
    APP_VERSION: str = "0.2.0"
    ENVIRONMENT: str = "development"
    SECRET_KEY: str = "change-me"
    CORS_ORIGINS: str = "http://localhost,http://localhost:5173,http://localhost:3000"

    # URLs
    FRONTEND_URL: str = "http://localhost:5173"
    BACKEND_URL: str = "http://localhost:8000"
    API_V1_PREFIX: str = "/api"

    # Database (PostgreSQL per MASTER_SPEC §2; async driver)
    DATABASE_URL: str = "postgresql+asyncpg://netgeo:netgeo@localhost:5432/netgeo"

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

    # Auth — JWT
    # HS256 with SECRET_KEY is the chosen algorithm (single-node; no RS256 keypair files needed).
    # ACCESS_TOKEN_EXPIRE_MINUTES controls JWT lifetime.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Auth — admin seed account (RB-01)
    # NETGEO_ADMIN_USER and NETGEO_ADMIN_PASSWORD are read once at startup.
    # If NETGEO_ADMIN_PASSWORD is empty, an ephemeral password is auto-generated
    # and printed to stderr — set it explicitly before any production use.
    NETGEO_ADMIN_USER: str = "admin"
    NETGEO_ADMIN_PASSWORD: str = ""

    # In-app self-update (see app/services/updater.py + scripts/self-update.sh).
    # GITHUB_REPO is the "owner/name" slug whose releases we compare against.
    GITHUB_REPO: str = "suryaex/netgeo"
    UPDATE_BRANCH: str = "main"
    # Shared secret required to call POST /api/update/apply.
    # An authenticated session is also required (see RB-05).
    UPDATE_TOKEN: str = ""
    # Sentinel + status files exchanged with the host-side scripts/self-update.sh.
    UPDATE_TRIGGER_FILE: str = "/var/lib/netgeo/update.request"
    UPDATE_STATUS_FILE: str = "/var/lib/netgeo/update.status"
    # When "1" the backend may run scripts/self-update.sh itself (needs the repo +
    # docker socket mounted). Otherwise it only drops the trigger file for a
    # host-side watcher to pick up — the safer default in containers.
    UPDATE_INPROC: bool = False

    # ---------------------------------------------------------------------------
    # Validators
    # ---------------------------------------------------------------------------

    @field_validator("ENABLE_HSTS", "UPDATE_INPROC", mode="before")
    @classmethod
    def _parse_bool(cls, v):  # noqa: ANN001
        if isinstance(v, str):
            return v.strip().lower() in {"1", "true", "yes", "on"}
        return v

    @model_validator(mode="after")
    def _check_secret_key(self) -> "Settings":
        """RB-07: Refuse to start in production with the default SECRET_KEY.

        In non-production environments, print a prominent warning to stderr so
        the developer sees it even before the logging system is configured.
        """
        if self.SECRET_KEY == "change-me":
            if self.ENVIRONMENT == "production":
                raise ValueError(
                    "[FATAL] SECRET_KEY is set to the insecure default 'change-me'. "
                    "This is not allowed in production. "
                    "Set SECRET_KEY to a cryptographically random string of at least "
                    "32 characters in your environment or .env file before deploying."
                )
            # Non-production: warn loudly — stderr is always visible.
            print(
                "\n"
                "*** SECURITY WARNING ***\n"
                "SECRET_KEY is 'change-me' (the insecure default).\n"
                "Any party who knows this default value can forge JWT tokens.\n"
                "Set SECRET_KEY to a unique random string before deploying.\n"
                "Example: SECRET_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')\n"
                "*** SECURITY WARNING ***\n",
                file=sys.stderr,
                flush=True,
            )
        return self

    # ---------------------------------------------------------------------------
    # Properties
    # ---------------------------------------------------------------------------

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
