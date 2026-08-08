"""Environment configuration.

Every secret is read from the environment, never from a committed file. See
``.env.example`` for the contract and ``../AI_PROJECTS.md`` rule 1.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Model choice follows ../AI_PROJECTS.md: Sonnet for parsing/classification,
# Haiku for high-volume cheap passes. Overridable per deployment without a code
# change, because model IDs move faster than releases do.
DEFAULT_PARSE_MODEL = "claude-sonnet-5"

# A drink extraction returns a handful of small objects. The default anyone
# copies from a tutorial is an order of magnitude too large for this.
DEFAULT_PARSE_MAX_TOKENS = 2048


class ConfigError(RuntimeError):
    """Raised when a required environment variable is missing."""


def require(name: str) -> str:
    """Return an environment variable, or fail with a message naming it."""
    value = os.environ.get(name)
    if not value:
        raise ConfigError(
            f"{name} is not set. Copy .env.example to .env and fill it in."
        )
    return value


def optional(name: str, default: str = "") -> str:
    """Return an environment variable or a default."""
    return os.environ.get(name) or default


@dataclass(frozen=True, slots=True)
class Settings:
    """Resolved runtime configuration."""

    anthropic_api_key: str
    telegram_bot_token: str
    line_channel_access_token: str
    line_channel_secret: str
    db_path: str
    link_base_url: str
    parse_model: str = DEFAULT_PARSE_MODEL
    parse_max_tokens: int = DEFAULT_PARSE_MAX_TOKENS

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from the environment.

        Telegram and LINE credentials are optional so a single-platform
        deployment does not have to carry the other platform's secrets.
        """
        return cls(
            anthropic_api_key=require("ANTHROPIC_API_KEY"),
            telegram_bot_token=optional("TELEGRAM_BOT_TOKEN"),
            line_channel_access_token=optional("LINE_CHANNEL_ACCESS_TOKEN"),
            line_channel_secret=optional("LINE_CHANNEL_SECRET"),
            db_path=optional("HYDRATION_DB_PATH", "./hydration.sqlite3"),
            link_base_url=optional("HYDRATION_LINK_BASE_URL", "https://link.example.com"),
            parse_model=optional("HYDRATION_PARSE_MODEL", DEFAULT_PARSE_MODEL),
            parse_max_tokens=int(
                optional("HYDRATION_PARSE_MAX_TOKENS", str(DEFAULT_PARSE_MAX_TOKENS))
            ),
        )
