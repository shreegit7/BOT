from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class GuildConfig:
    guild_id: int
    quiz_channel_id: int | None = None
    levelup_channel_id: int | None = None
    leaderboard_channel_id: int | None = None
    leaderboard_message_id: int | None = None
    daily_quiz_time: str = "20:00"
    chat_xp_enabled: bool = True
    voice_xp_enabled: bool = True
    min_quiz_players: int = 2
    quiz_cooldown_minutes: int = 10
    leaderboard_update_minutes: int = 5
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
    last_daily_quiz_run_date: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, object]) -> "GuildConfig":
        return cls(
            guild_id=int(row["guild_id"]),
            quiz_channel_id=int(row["quiz_channel_id"]) if row["quiz_channel_id"] else None,
            levelup_channel_id=(
                int(row["levelup_channel_id"]) if row["levelup_channel_id"] else None
            ),
            leaderboard_channel_id=(
                int(row["leaderboard_channel_id"]) if row["leaderboard_channel_id"] else None
            ),
            leaderboard_message_id=(
                int(row["leaderboard_message_id"]) if row["leaderboard_message_id"] else None
            ),
            daily_quiz_time=str(row["daily_quiz_time"]),
            chat_xp_enabled=bool(row["chat_xp_enabled"]),
            voice_xp_enabled=bool(row["voice_xp_enabled"]),
            min_quiz_players=int(row["min_quiz_players"]),
            quiz_cooldown_minutes=int(row["quiz_cooldown_minutes"]),
            leaderboard_update_minutes=int(row["leaderboard_update_minutes"]),
            voice_xp_interval_minutes=int(row["voice_xp_interval_minutes"]),
            voice_xp_base=int(row["voice_xp_base"]),
            voice_xp_group_bonus=int(row["voice_xp_group_bonus"]),
            voice_group_bonus_threshold=int(row["voice_group_bonus_threshold"]),
            chat_xp_min=int(row["chat_xp_min"]),
            chat_xp_max=int(row["chat_xp_max"]),
            chat_xp_cooldown_seconds=int(row["chat_xp_cooldown_seconds"]),
            min_message_length=int(row["min_message_length"]),
            ignore_command_messages=bool(row["ignore_command_messages"]),
            allow_muted_voice=bool(row["allow_muted_voice"]),
            disallow_self_deafened=bool(row["disallow_self_deafened"]),
            ignore_afk_channel=bool(row["ignore_afk_channel"]),
            default_quiz_category=str(row["default_quiz_category"]),
            lobby_duration_seconds=int(row["lobby_duration_seconds"]),
            questions_per_quiz=int(row["questions_per_quiz"]),
            question_time_limit_seconds=int(row["question_time_limit_seconds"]),
            last_daily_quiz_run_date=(
                str(row["last_daily_quiz_run_date"])
                if row["last_daily_quiz_run_date"]
                else None
            ),
        )


@dataclass(slots=True)
class UserStats:
    guild_id: int
    user_id: int
    total_xp: int
    chat_xp: int
    voice_xp: int
    quiz_xp: int
    level: int
    messages_count: int
    total_voice_minutes: int
    quiz_wins: int
    quizzes_played: int
    correct_answers: int
    daily_quiz_streak: int
    last_daily_quiz_date: str | None
    title_label: str = ""

    @classmethod
    def from_row(cls, row: dict[str, object]) -> "UserStats":
        return cls(
            guild_id=int(row["guild_id"]),
            user_id=int(row["user_id"]),
            total_xp=int(row["total_xp"]),
            chat_xp=int(row["chat_xp"]),
            voice_xp=int(row["voice_xp"]),
            quiz_xp=int(row["quiz_xp"]),
            level=int(row["level"]),
            messages_count=int(row["messages_count"]),
            total_voice_minutes=int(row["total_voice_minutes"]),
            quiz_wins=int(row["quiz_wins"]),
            quizzes_played=int(row["quizzes_played"]),
            correct_answers=int(row["correct_answers"]),
            daily_quiz_streak=int(row["daily_quiz_streak"]),
            last_daily_quiz_date=(
                str(row["last_daily_quiz_date"]) if row["last_daily_quiz_date"] else None
            ),
            title_label=str(row["title_label"] or ""),
        )


@dataclass(slots=True)
class LevelUpEvent:
    guild_id: int
    user_id: int
    old_level: int
    new_level: int
    awarded_roles: list[int] = field(default_factory=list)


@dataclass(slots=True)
class LeaderboardEntry:
    user_id: int
    value: int
    level: int | None = None
    rank: int = 0


@dataclass(slots=True)
class TriviaQuestion:
    question: str
    correct_answer: str
    options: list[str]
    correct_index: int
    category: str


@dataclass(slots=True)
class AnswerRecord:
    choice_index: int
    is_correct: bool
    response_seconds: float
    answered_at: datetime


@dataclass(slots=True)
class QuizPlayerState:
    user_id: int
    score: int = 0
    correct_count: int = 0
    fast_bonus_count: int = 0
    answers: dict[int, AnswerRecord] = field(default_factory=dict)
