from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(slots=True, frozen=True)
class DefaultGuildSettings:
    daily_quiz_time: str = "20:00"
    min_quiz_players: int = 2
    quiz_cooldown_minutes: int = 10
    voice_xp_interval_minutes: int = 5
    voice_xp_base: int = 5
    voice_xp_group_bonus: int = 7
    voice_group_bonus_threshold: int = 4
    chat_xp_min: int = 6
    chat_xp_max: int = 10
    chat_xp_cooldown_seconds: int = 45
    min_message_length: int = 12
    ignore_command_messages: bool = True
    allow_muted_voice: bool = True
    disallow_self_deafened: bool = True
    ignore_afk_channel: bool = True
    default_quiz_category: str = "general"
    lobby_duration_seconds: int = 30
    questions_per_quiz: int = 5
    question_time_limit_seconds: int = 15


@dataclass(slots=True, frozen=True)
class QuizScoring:
    participation_xp: int = 10
    correct_answer_xp: int = 15
    fast_answer_bonus_xp: int = 5
    winner_bonus_xp: int = 25
    daily_streak_bonus_xp: int = 10


@dataclass(slots=True, frozen=True)
class AppConfig:
    discord_token: str
    quizapi_key: str
    database_path: str
    timezone: str
    default_prefix: str
    log_level: str
    enable_healthcheck: bool
    health_port: int
    sync_commands_on_startup: bool
    defaults: DefaultGuildSettings = field(default_factory=DefaultGuildSettings)
    scoring: QuizScoring = field(default_factory=QuizScoring)

    @classmethod
    def load(cls) -> "AppConfig":
        load_dotenv()

        discord_token = (os.getenv("DISCORD_TOKEN") or "").strip()
        if not discord_token:
            raise ValueError("Missing DISCORD_TOKEN in environment.")

        quizapi_key = (os.getenv("QUIZAPI_KEY") or "").strip()
        if not quizapi_key:
            quizapi_key = ""

        port_env = os.getenv("PORT")
        health_default = bool(port_env)
        enable_healthcheck = _parse_bool(
            os.getenv("HEALTHCHECK_ENABLED"), default=health_default
        )
        health_port = int((os.getenv("HEALTH_PORT") or port_env or "8080").strip())

        return cls(
            discord_token=discord_token,
            quizapi_key=quizapi_key,
            database_path=str(
                Path(os.getenv("DATABASE_PATH", "data/bot.db")).expanduser().resolve()
            ),
            timezone=os.getenv("TZ", "UTC").strip(),
            default_prefix=os.getenv("DEFAULT_PREFIX", "!").strip(),
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
            enable_healthcheck=enable_healthcheck,
            health_port=health_port,
            sync_commands_on_startup=_parse_bool(
                os.getenv("SYNC_COMMANDS_ON_STARTUP"), default=True
            ),
        )
