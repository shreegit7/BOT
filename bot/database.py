from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Iterable

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS guild_config (
    guild_id INTEGER PRIMARY KEY,
    quiz_channel_id INTEGER,
    levelup_channel_id INTEGER,
    leaderboard_channel_id INTEGER,
    leaderboard_message_id INTEGER,
    daily_quiz_time TEXT NOT NULL DEFAULT '20:00',
    chat_xp_enabled INTEGER NOT NULL DEFAULT 1,
    voice_xp_enabled INTEGER NOT NULL DEFAULT 1,
    min_quiz_players INTEGER NOT NULL DEFAULT 2,
    quiz_cooldown_minutes INTEGER NOT NULL DEFAULT 10,
    leaderboard_update_minutes INTEGER NOT NULL DEFAULT 5,
    voice_xp_interval_minutes INTEGER NOT NULL DEFAULT 5,
    voice_xp_base INTEGER NOT NULL DEFAULT 5,
    voice_xp_group_bonus INTEGER NOT NULL DEFAULT 7,
    voice_group_bonus_threshold INTEGER NOT NULL DEFAULT 4,
    chat_xp_min INTEGER NOT NULL DEFAULT 6,
    chat_xp_max INTEGER NOT NULL DEFAULT 10,
    chat_xp_cooldown_seconds INTEGER NOT NULL DEFAULT 45,
    min_message_length INTEGER NOT NULL DEFAULT 12,
    ignore_command_messages INTEGER NOT NULL DEFAULT 1,
    allow_muted_voice INTEGER NOT NULL DEFAULT 1,
    disallow_self_deafened INTEGER NOT NULL DEFAULT 1,
    ignore_afk_channel INTEGER NOT NULL DEFAULT 1,
    default_quiz_category TEXT NOT NULL DEFAULT 'general',
    lobby_duration_seconds INTEGER NOT NULL DEFAULT 30,
    questions_per_quiz INTEGER NOT NULL DEFAULT 5,
    question_time_limit_seconds INTEGER NOT NULL DEFAULT 15,
    last_daily_quiz_run_date TEXT
);

CREATE TABLE IF NOT EXISTS user_stats (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    total_xp INTEGER NOT NULL DEFAULT 0,
    chat_xp INTEGER NOT NULL DEFAULT 0,
    voice_xp INTEGER NOT NULL DEFAULT 0,
    quiz_xp INTEGER NOT NULL DEFAULT 0,
    level INTEGER NOT NULL DEFAULT 1,
    messages_count INTEGER NOT NULL DEFAULT 0,
    total_voice_minutes INTEGER NOT NULL DEFAULT 0,
    quiz_wins INTEGER NOT NULL DEFAULT 0,
    quizzes_played INTEGER NOT NULL DEFAULT 0,
    correct_answers INTEGER NOT NULL DEFAULT 0,
    daily_quiz_streak INTEGER NOT NULL DEFAULT 0,
    last_daily_quiz_date TEXT,
    title_label TEXT DEFAULT '',
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS voice_sessions (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    channel_id INTEGER,
    joined_at TEXT NOT NULL,
    last_checked_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS quiz_sessions (
    session_id TEXT PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    host_user_id INTEGER NOT NULL,
    quiz_type TEXT NOT NULL,
    category TEXT NOT NULL,
    question_count INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quiz_participants (
    session_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    score INTEGER NOT NULL DEFAULT 0,
    correct_count INTEGER NOT NULL DEFAULT 0,
    fast_bonus_count INTEGER NOT NULL DEFAULT 0,
    joined_at TEXT NOT NULL,
    PRIMARY KEY (session_id, user_id),
    FOREIGN KEY (session_id) REFERENCES quiz_sessions(session_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS level_roles (
    guild_id INTEGER NOT NULL,
    level_threshold INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    title_label TEXT DEFAULT '',
    PRIMARY KEY (guild_id, level_threshold)
);

CREATE TABLE IF NOT EXISTS quiz_answers (
    session_id TEXT NOT NULL,
    question_index INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    response_ms INTEGER NOT NULL,
    is_correct INTEGER NOT NULL,
    answered_at TEXT NOT NULL,
    PRIMARY KEY (session_id, question_index, user_id),
    FOREIGN KEY (session_id) REFERENCES quiz_sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_stats_total_xp
    ON user_stats(guild_id, total_xp DESC);
CREATE INDEX IF NOT EXISTS idx_user_stats_voice_xp
    ON user_stats(guild_id, voice_xp DESC);
CREATE INDEX IF NOT EXISTS idx_user_stats_quiz_xp
    ON user_stats(guild_id, quiz_xp DESC);
CREATE INDEX IF NOT EXISTS idx_quiz_sessions_guild_status
    ON quiz_sessions(guild_id, status, ended_at);
CREATE INDEX IF NOT EXISTS idx_quiz_answers_user
    ON quiz_answers(user_id, answered_at);
"""


class Database:
    def __init__(self, database_path: str) -> None:
        self.database_path = Path(database_path)
        self._connection: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            str(self.database_path), check_same_thread=False, isolation_level=None
        )
        self._connection.row_factory = sqlite3.Row
        await self.executescript(SCHEMA_SQL)
        await self._run_migrations()

    async def close(self) -> None:
        if self._connection is None:
            return
        connection = self._connection
        self._connection = None
        await asyncio.to_thread(connection.close)

    async def execute(self, query: str, params: Iterable[object] = ()) -> None:
        async with self._lock:
            await asyncio.to_thread(self._execute_sync, query, tuple(params))

    async def executemany(
        self, query: str, params_list: Iterable[Iterable[object]]
    ) -> None:
        async with self._lock:
            await asyncio.to_thread(self._executemany_sync, query, params_list)

    async def fetchone(
        self, query: str, params: Iterable[object] = ()
    ) -> sqlite3.Row | None:
        async with self._lock:
            return await asyncio.to_thread(self._fetchone_sync, query, tuple(params))

    async def fetchall(
        self, query: str, params: Iterable[object] = ()
    ) -> list[sqlite3.Row]:
        async with self._lock:
            rows = await asyncio.to_thread(self._fetchall_sync, query, tuple(params))
        return list(rows)

    async def executescript(self, script: str) -> None:
        async with self._lock:
            await asyncio.to_thread(self._executescript_sync, script)

    def _connection_or_raise(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("Database connection is not initialized.")
        return self._connection

    def _execute_sync(self, query: str, params: tuple[object, ...]) -> None:
        connection = self._connection_or_raise()
        connection.execute(query, params)

    def _executemany_sync(
        self, query: str, params_list: Iterable[Iterable[object]]
    ) -> None:
        connection = self._connection_or_raise()
        connection.executemany(query, params_list)

    def _fetchone_sync(
        self, query: str, params: tuple[object, ...]
    ) -> sqlite3.Row | None:
        connection = self._connection_or_raise()
        cursor = connection.execute(query, params)
        row = cursor.fetchone()
        cursor.close()
        return row

    def _fetchall_sync(self, query: str, params: tuple[object, ...]) -> list[sqlite3.Row]:
        connection = self._connection_or_raise()
        cursor = connection.execute(query, params)
        rows = cursor.fetchall()
        cursor.close()
        return rows

    def _executescript_sync(self, script: str) -> None:
        connection = self._connection_or_raise()
        connection.executescript(script)

    async def _run_migrations(self) -> None:
        columns = await self.fetchall("PRAGMA table_info(guild_config)")
        existing = {str(row["name"]) for row in columns}

        migrations: list[str] = []
        if "leaderboard_channel_id" not in existing:
            migrations.append("ALTER TABLE guild_config ADD COLUMN leaderboard_channel_id INTEGER")
        if "leaderboard_message_id" not in existing:
            migrations.append("ALTER TABLE guild_config ADD COLUMN leaderboard_message_id INTEGER")
        if "leaderboard_update_minutes" not in existing:
            migrations.append(
                "ALTER TABLE guild_config ADD COLUMN leaderboard_update_minutes INTEGER NOT NULL DEFAULT 5"
            )

        for statement in migrations:
            await self.execute(statement)
