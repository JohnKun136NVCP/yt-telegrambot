"""Centralized, validated configuration loaded from environment variables.

``main.py`` calls ``load_dotenv()`` and then ``load_config()`` once at
startup; any missing/invalid value raises ``ConfigError`` with a message a
non-programmer can act on, instead of the bot crashing minutes later with a
confusing traceback. Every other module reads values through
``get_config()``, which returns that same validated instance.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


# =============================================================================
# Env parsing helpers
# =============================================================================

def _split_ids(raw: str | None) -> frozenset[int]:
    if not raw:
        return frozenset()

    ids = set()

    for chunk in raw.split(","):
        chunk = chunk.strip()

        if not chunk:
            continue

        if not chunk.lstrip("-").isdigit():
            raise ConfigError(f"Invalid Telegram user id in ADMIN_IDS: {chunk!r}")

        ids.add(int(chunk))

    return frozenset(ids)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)

    if raw is None or not raw.strip():
        return default

    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from None


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)

    if raw is None or not raw.strip():
        return default

    try:
        return float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)

    if raw is None or not raw.strip():
        return default

    return raw.strip().lower() in {"1", "true", "yes", "on"}


# =============================================================================
# Stars (Telegram's in-app currency) subscription plans
# =============================================================================

@dataclass(frozen=True)
class StarPlan:
    code: str
    label: str
    days: int
    stars: int


# Placeholder pricing: the bot owner should tune these (via STAR_PLANS in
# .env) to whatever is sustainable. 1 Telegram Star is roughly $0.013 USD,
# set by Telegram and not something this bot controls.
DEFAULT_PLANS = (
    StarPlan("p7", "1 week", 7, 150),
    StarPlan("p30", "1 month", 30, 450),
    StarPlan("p365", "1 year", 365, 4000),
)


def _load_plans() -> tuple[StarPlan, ...]:
    raw = os.getenv("STAR_PLANS")

    if not raw or not raw.strip():
        return DEFAULT_PLANS

    plans = []

    # Format: "code:label:days:stars,code:label:days:stars,..."
    for item in raw.split(","):
        parts = item.split(":")

        if len(parts) != 4:
            raise ConfigError(
                "STAR_PLANS entries must look like code:label:days:stars, "
                f"got {item!r}"
            )

        code, label, days, stars = (part.strip() for part in parts)

        if not code or not label:
            raise ConfigError(f"STAR_PLANS entry has an empty code/label: {item!r}")

        try:
            days_int, stars_int = int(days), int(stars)
        except ValueError:
            raise ConfigError(f"Invalid days/stars in STAR_PLANS entry: {item!r}") from None

        if days_int <= 0 or stars_int <= 0:
            raise ConfigError(f"days/stars must be positive in STAR_PLANS entry: {item!r}")

        plans.append(StarPlan(code, label, days_int, stars_int))

    codes = [plan.code for plan in plans]

    if len(codes) != len(set(codes)):
        raise ConfigError("STAR_PLANS has duplicate plan codes.")

    return tuple(plans)


# =============================================================================
# Config
# =============================================================================

@dataclass(frozen=True)
class Config:
    token: str
    admin_ids: frozenset[int]

    # Local Telegram Bot API server (see scripts/setup.sh). None = use
    # Telegram's cloud API, which hard-caps uploads/downloads at 50 MB/20 MB
    # no matter what the bot sends.
    bot_api_base_url: str | None
    bot_api_base_file_url: str | None
    bot_api_local_mode: bool

    standard_max_mb: float
    premium_max_mb: float

    queue_max_size: int
    queue_workers: int
    job_timeout_seconds: float

    min_seconds_between_requests: float

    plans: tuple[StarPlan, ...]

    @property
    def uses_local_server(self) -> bool:
        return self.bot_api_base_url is not None

    def effective_premium_max_mb(self) -> float:
        """The real premium cap this bot can actually deliver.

        Telegram's cloud Bot API hard-caps uploads at 50 MB no matter what a
        bot sends, regardless of the user's plan. Only a self-hosted local
        Bot API server (``--local`` mode) can accept more, up to 2000 MB.
        Without one configured, premium users still get the standard cap --
        advertising a limit the bot cannot physically deliver would just
        produce confusing upload failures.
        """
        if not self.uses_local_server:
            return self.standard_max_mb

        return self.premium_max_mb

    def plan(self, code: str) -> StarPlan | None:
        return next((plan for plan in self.plans if plan.code == code), None)


def load_config() -> Config:
    """Build a ``Config`` from environment variables, failing fast on errors."""
    token = os.getenv("TOKEN", "").strip()

    if not token:
        raise ConfigError(
            "TOKEN is not set. Create a bot with @BotFather on Telegram and "
            "put its token in a .env file as TOKEN=... "
            "(see .env-example, or run scripts/setup.sh)."
        )

    # Local Bot API server host, e.g. "http://127.0.0.1:8081" -- no "/bot"
    # suffix, no trailing slash. The method/file paths are derived below
    # using the same convention telegram-bot-api itself uses.
    base_host = (os.getenv("BOT_API_BASE_URL") or "").strip().rstrip("/") or None

    config = Config(
        token=token,
        admin_ids=_split_ids(os.getenv("ADMIN_IDS")),
        bot_api_base_url=f"{base_host}/bot" if base_host else None,
        bot_api_base_file_url=f"{base_host}/file/bot" if base_host else None,
        bot_api_local_mode=_env_bool("BOT_API_LOCAL_MODE", default=bool(base_host)),
        standard_max_mb=_env_float("STANDARD_MAX_MB", 49.5),
        premium_max_mb=_env_float("PREMIUM_MAX_MB", 1900.0),
        queue_max_size=_env_int("QUEUE_MAX_SIZE", 50),
        queue_workers=_env_int("QUEUE_WORKERS", 2),
        job_timeout_seconds=_env_float("JOB_TIMEOUT_SECONDS", 1800.0),
        min_seconds_between_requests=_env_float("MIN_SECONDS_BETWEEN_REQUESTS", 3.0),
        plans=_load_plans(),
    )

    if config.standard_max_mb <= 0 or config.premium_max_mb <= 0:
        raise ConfigError("STANDARD_MAX_MB and PREMIUM_MAX_MB must be positive.")

    if config.premium_max_mb < config.standard_max_mb:
        raise ConfigError("PREMIUM_MAX_MB cannot be smaller than STANDARD_MAX_MB.")

    if config.queue_max_size < 1 or config.queue_workers < 1:
        raise ConfigError("QUEUE_MAX_SIZE and QUEUE_WORKERS must be at least 1.")

    if config.job_timeout_seconds <= 0:
        raise ConfigError("JOB_TIMEOUT_SECONDS must be positive.")

    if config.min_seconds_between_requests < 0:
        raise ConfigError("MIN_SECONDS_BETWEEN_REQUESTS cannot be negative.")

    return config


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Return the process-wide config, loading (and validating) it on first use."""
    return load_config()


def reset_config_cache() -> None:
    """Testing helper: forget the cached config so the next ``get_config()``
    call re-reads the environment."""
    get_config.cache_clear()
