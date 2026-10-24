from __future__ import annotations
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = BASE_DIR / "config"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), env_file_encoding="utf-8", extra="ignore")

    # SQLite is the preserved default; set DATABASE_URL to override (PostgreSQL
    # remains possible for deployments but is never required).
    DATABASE_URL: str = f"sqlite+aiosqlite:///{BASE_DIR / 'trends.db'}"
    SYNC_DATABASE_URL: str = f"sqlite:///{BASE_DIR / 'trends.db'}"
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    HALF_LIFE_DAYS: int | None = None
    TREND_SIMILARITY_THRESHOLD: float | None = None
    WINDOW_DAYS: int | None = None
    LLM_ENABLED: bool | None = None
    LLM_PROVIDER: str | None = None
    LLM_MODEL: str | None = None
    LLM_API_KEY: str | None = None
    LLM_API_BASE: str | None = None
    LLM_MAX_CALLS_PER_DAY: int | None = None
    USER_AGENT: str = "FashionTrendBot/1.0 (+https://example.com/bot)"
    DEFAULT_TIMEOUT: int = 15
    # Collection / scheduling (optional; disabled by default so the module never
    # starts a background job inside the API process unless explicitly asked).
    TREND_SCHEDULER_ENABLED: bool = False
    TREND_SNAPSHOT_INTERVAL_HOURS: int = 6
    TREND_COLLECTION_MAX_URLS: int = 5
    TREND_RATE_LIMIT_DELAY: float = 2.0
    EXCLUDE_SYNTHETIC: bool = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_sources_config() -> dict:
    return load_yaml("sources.yaml")


def get_scoring_config() -> dict:
    data = load_yaml("scoring.yaml")
    cfg = data["scoring"] if "scoring" in data else data
    # Env overrides for configurable thresholds (never hard-code secrets/thresholds)
    env_half = os.getenv("HALF_LIFE_DAYS")
    if env_half is None:
        try:
            v = get_settings().HALF_LIFE_DAYS
            env_half = str(v) if v is not None else None
        except Exception:
            env_half = None
    if env_half is not None:
        try:
            iv = int(env_half)
            cfg["half_life_days"] = iv
            if "recency" in cfg:
                cfg["recency"]["half_life_days"] = iv
        except ValueError:
            pass
    env_sim = os.getenv("TREND_SIMILARITY_THRESHOLD")
    if env_sim is None:
        try:
            v = get_settings().TREND_SIMILARITY_THRESHOLD
            env_sim = str(v) if v is not None else None
        except Exception:
            env_sim = None
    if env_sim is not None:
        try:
            cfg["similarity_threshold"] = float(env_sim)
        except ValueError:
            pass
    env_window = os.getenv("WINDOW_DAYS")
    if env_window is None:
        try:
            v = get_settings().WINDOW_DAYS
            env_window = str(v) if v is not None else None
        except Exception:
            env_window = None
    if env_window is not None:
        try:
            cfg["window_days"] = int(env_window)
        except ValueError:
            pass
    return cfg


def get_taxonomy_config() -> dict:
    return load_yaml("taxonomy.yaml")


def get_seasonal_config() -> dict:
    return load_yaml("seasonal_affinity.yaml")


def get_llm_config() -> dict:
    data = load_yaml("llm.yaml")
    if "llm" in data:
        return data["llm"]
    return data
