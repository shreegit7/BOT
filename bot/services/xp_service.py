from __future__ import annotations

import asyncio
import logging
import random
from collections import defaultdict, deque
from datetime import datetime, timedelta

import discord

from bot.config import AppConfig
from bot.database import Database
from bot.models import GuildConfig, LeaderboardEntry, LevelUpEvent, UserStats
from bot.utils.formatting import Theme, normalize_for_spam_check
from bot.utils.levels import level_from_total_xp
from bot.utils.time import utc_now

LOGGER = logging.getLogger(__name__)


class XPService:
    def __init__(self, database: Database, config: AppConfig) -> None:
        self.db = database
        self.config = config
        self._guild_cache: dict[int, GuildConfig] = {}
        self._message_cooldowns: dict[tuple[int, int], datetime] = {}
        self._recent_messages: dict[tuple[int, int], deque[tuple[str, datetime]]] = defaultdict(
            lambda: deque(maxlen=5)
        )
        self._xp_locks: dict[tuple[int, int], asyncio.Lock] = {}

    async def get_guild_config(self, guild_id: int, force_refresh: bool = False) -> GuildConfig:
        if not force_refresh and guild_id in self._guild_cache:
            return self._guild_cache[guild_id]

        await self._ensure_guild_config_exists(guild_id)
        row = await self.db.fetchone("SELECT * FROM guild_config WHERE guild_id = ?", (guild_id,))
        if row is None:
            raise RuntimeError(f"Failed to read guild_config for guild_id={guild_id}")
        config = GuildConfig.from_row(dict(row))
        self._guild_cache[guild_id] = config
        return config

    async def update_guild_config_field(self, guild_id: int, field: str, value: object) -> GuildConfig:
        allowed = {
            "quiz_channel_id",
            "levelup_channel_id",
            "leaderboard_channel_id",
            "leaderboard_message_id",
            "daily_quiz_time",
            "chat_xp_enabled",
            "voice_xp_enabled",
            "min_quiz_players",
            "quiz_cooldown_minutes",
            "leaderboard_update_minutes",
            "voice_xp_interval_minutes",
            "voice_xp_base",
            "voice_xp_group_bonus",
            "voice_group_bonus_threshold",
            "chat_xp_min",
            "chat_xp_max",
            "chat_xp_cooldown_seconds",
            "min_message_length",
            "ignore_command_messages",
            "allow_muted_voice",
            "disallow_self_deafened",
            "ignore_afk_channel",
            "default_quiz_category",
            "lobby_duration_seconds",
            "questions_per_quiz",
            "question_time_limit_seconds",
            "last_daily_quiz_run_date",
        }
        if field not in allowed:
            raise ValueError(f"Unsupported guild config field: {field}")

        await self._ensure_guild_config_exists(guild_id)
        await self.db.execute(
            f"UPDATE guild_config SET {field} = ? WHERE guild_id = ?",
            (value, guild_id),
        )
        return await self.get_guild_config(guild_id, force_refresh=True)

    async def set_level_role(
        self, guild_id: int, level_threshold: int, role_id: int, title_label: str = ""
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO level_roles (guild_id, level_threshold, role_id, title_label)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, level_threshold)
            DO UPDATE SET role_id = excluded.role_id, title_label = excluded.title_label
            """,
            (guild_id, level_threshold, role_id, title_label.strip()),
        )

    async def get_level_roles(self, guild_id: int) -> list[tuple[int, int, str]]:
        rows = await self.db.fetchall(
            """
            SELECT level_threshold, role_id, title_label
            FROM level_roles
            WHERE guild_id = ?
            ORDER BY level_threshold ASC
            """,
            (guild_id,),
        )
        return [(int(r["level_threshold"]), int(r["role_id"]), str(r["title_label"] or "")) for r in rows]

    async def get_user_stats(self, guild_id: int, user_id: int) -> UserStats:
        await self._ensure_user_stats_exists(guild_id, user_id)
        row = await self.db.fetchone(
            "SELECT * FROM user_stats WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        if row is None:
            raise RuntimeError("Unable to fetch user_stats after ensure step.")
        return UserStats.from_row(dict(row))

    async def process_message_xp(self, message: discord.Message) -> LevelUpEvent | None:
        if not message.guild or not message.author or message.author.bot:
            return None

        guild_id = message.guild.id
        user_id = message.author.id
        cfg = await self.get_guild_config(guild_id)
        if not cfg.chat_xp_enabled:
            return None

        content = (message.content or "").strip()
        if len(content) < cfg.min_message_length:
            return None

        if cfg.ignore_command_messages and self._looks_like_command(content):
            return None

        now = utc_now()
        cooldown_key = (guild_id, user_id)
        last_award_at = self._message_cooldowns.get(cooldown_key)
        if last_award_at:
            elapsed = (now - last_award_at).total_seconds()
            if elapsed < cfg.chat_xp_cooldown_seconds:
                return None

        if self._is_repeated_spam(cooldown_key, content, now):
            return None

        xp_award = random.randint(cfg.chat_xp_min, cfg.chat_xp_max)
        event = await self.add_xp(
            guild_id=guild_id,
            user_id=user_id,
            amount=xp_award,
            xp_type="chat_xp",
            guild=message.guild,
            member=message.author if isinstance(message.author, discord.Member) else None,
            allow_levelup_announce=True,
        )
        await self.db.execute(
            """
            UPDATE user_stats
            SET messages_count = messages_count + 1
            WHERE guild_id = ? AND user_id = ?
            """,
            (guild_id, user_id),
        )
        self._message_cooldowns[cooldown_key] = now
        return event

    async def add_xp(
        self,
        *,
        guild_id: int,
        user_id: int,
        amount: int,
        xp_type: str,
        guild: discord.Guild | None = None,
        member: discord.Member | None = None,
        allow_levelup_announce: bool = True,
    ) -> LevelUpEvent | None:
        if amount <= 0:
            return None

        safe_amount = min(500, int(amount))
        if xp_type not in {"chat_xp", "voice_xp", "quiz_xp"}:
            raise ValueError(f"Invalid xp_type: {xp_type}")

        lock = self._xp_locks.setdefault((guild_id, user_id), asyncio.Lock())
        async with lock:
            await self._ensure_user_stats_exists(guild_id, user_id)
            row = await self.db.fetchone(
                """
                SELECT total_xp, chat_xp, voice_xp, quiz_xp, level
                FROM user_stats
                WHERE guild_id = ? AND user_id = ?
                """,
                (guild_id, user_id),
            )
            if row is None:
                return None

            old_total = int(row["total_xp"])
            old_level = int(row["level"])
            new_total = old_total + safe_amount
            new_level = level_from_total_xp(new_total)

            updates = {
                "chat_xp": int(row["chat_xp"]),
                "voice_xp": int(row["voice_xp"]),
                "quiz_xp": int(row["quiz_xp"]),
            }
            updates[xp_type] += safe_amount

            await self.db.execute(
                """
                UPDATE user_stats
                SET total_xp = ?, chat_xp = ?, voice_xp = ?, quiz_xp = ?, level = ?
                WHERE guild_id = ? AND user_id = ?
                """,
                (
                    new_total,
                    updates["chat_xp"],
                    updates["voice_xp"],
                    updates["quiz_xp"],
                    new_level,
                    guild_id,
                    user_id,
                ),
            )

        if new_level <= old_level:
            return None

        event = LevelUpEvent(
            guild_id=guild_id,
            user_id=user_id,
            old_level=old_level,
            new_level=new_level,
        )
        if allow_levelup_announce:
            await self._handle_level_up(guild=guild, member=member, event=event)
        return event

    async def add_voice_minutes(self, guild_id: int, user_id: int, minutes: int) -> None:
        if minutes <= 0:
            return
        await self._ensure_user_stats_exists(guild_id, user_id)
        await self.db.execute(
            """
            UPDATE user_stats
            SET total_voice_minutes = total_voice_minutes + ?
            WHERE guild_id = ? AND user_id = ?
            """,
            (minutes, guild_id, user_id),
        )

    async def add_quiz_participation_stats(
        self,
        *,
        guild_id: int,
        user_id: int,
        correct_count: int,
        won: bool,
        quiz_type: str,
    ) -> None:
        await self._ensure_user_stats_exists(guild_id, user_id)
        await self.db.execute(
            """
            UPDATE user_stats
            SET quizzes_played = quizzes_played + 1,
                correct_answers = correct_answers + ?,
                quiz_wins = quiz_wins + ?
            WHERE guild_id = ? AND user_id = ?
            """,
            (max(0, correct_count), 1 if won else 0, guild_id, user_id),
        )

        if quiz_type != "daily":
            return

        today = utc_now().date()
        yesterday = today - timedelta(days=1)
        row = await self.db.fetchone(
            """
            SELECT daily_quiz_streak, last_daily_quiz_date
            FROM user_stats
            WHERE guild_id = ? AND user_id = ?
            """,
            (guild_id, user_id),
        )
        if row is None:
            return

        last_date_str = str(row["last_daily_quiz_date"]) if row["last_daily_quiz_date"] else None
        if last_date_str == today.isoformat():
            return

        current_streak = int(row["daily_quiz_streak"])
        if last_date_str == yesterday.isoformat():
            current_streak += 1
        else:
            current_streak = 1

        await self.db.execute(
            """
            UPDATE user_stats
            SET daily_quiz_streak = ?,
                last_daily_quiz_date = ?
            WHERE guild_id = ? AND user_id = ?
            """,
            (current_streak, today.isoformat(), guild_id, user_id),
        )

    async def get_rank_position(
        self, guild_id: int, user_id: int, metric: str = "overall", weekly: bool = False
    ) -> int | None:
        metric_column = self._metric_to_column(metric)
        if weekly and metric == "quiz":
            return await self._get_weekly_quiz_rank_position(guild_id, user_id)

        row = await self.db.fetchone(
            f"SELECT {metric_column} AS value FROM user_stats WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        if row is None:
            return None
        value = int(row["value"])
        position_row = await self.db.fetchone(
            f"""
            SELECT COUNT(*) + 1 AS rank
            FROM user_stats
            WHERE guild_id = ?
            AND ({metric_column} > ? OR ({metric_column} = ? AND user_id < ?))
            """,
            (guild_id, value, value, user_id),
        )
        return int(position_row["rank"]) if position_row else None

    async def get_leaderboard(
        self,
        guild_id: int,
        metric: str,
        *,
        limit: int,
        offset: int = 0,
        weekly: bool = False,
    ) -> list[LeaderboardEntry]:
        if weekly and metric == "quiz":
            return await self._get_weekly_quiz_leaderboard(guild_id, limit=limit, offset=offset)

        metric_column = self._metric_to_column(metric)
        rows = await self.db.fetchall(
            f"""
            SELECT user_id, {metric_column} AS value, level
            FROM user_stats
            WHERE guild_id = ?
            ORDER BY {metric_column} DESC, user_id ASC
            LIMIT ? OFFSET ?
            """,
            (guild_id, limit, offset),
        )

        entries: list[LeaderboardEntry] = []
        for index, row in enumerate(rows, start=offset + 1):
            entries.append(
                LeaderboardEntry(
                    user_id=int(row["user_id"]),
                    value=int(row["value"]),
                    level=int(row["level"]),
                    rank=index,
                )
            )
        return entries

    async def get_stats_leaderboard(
        self,
        guild_id: int,
        *,
        limit: int,
        offset: int = 0,
    ) -> list[dict[str, int]]:
        rows = await self.db.fetchall(
            """
            SELECT user_id, level, total_xp, chat_xp, voice_xp, quiz_xp, total_voice_minutes, quiz_wins
            FROM user_stats
            WHERE guild_id = ?
            ORDER BY total_xp DESC, user_id ASC
            LIMIT ? OFFSET ?
            """,
            (guild_id, limit, offset),
        )
        result: list[dict[str, int]] = []
        for row in rows:
            result.append(
                {
                    "user_id": int(row["user_id"]),
                    "level": int(row["level"]),
                    "total_xp": int(row["total_xp"]),
                    "chat_xp": int(row["chat_xp"]),
                    "voice_xp": int(row["voice_xp"]),
                    "quiz_xp": int(row["quiz_xp"]),
                    "total_voice_minutes": int(row["total_voice_minutes"]),
                    "quiz_wins": int(row["quiz_wins"]),
                }
            )
        return result

    async def count_users_for_metric(self, guild_id: int, metric: str, weekly: bool = False) -> int:
        if weekly and metric == "quiz":
            cutoff = (utc_now() - timedelta(days=7)).isoformat()
            row = await self.db.fetchone(
                """
                SELECT COUNT(*) AS total
                FROM (
                    SELECT qp.user_id
                    FROM quiz_participants qp
                    INNER JOIN quiz_sessions qs ON qs.session_id = qp.session_id
                    WHERE qs.guild_id = ?
                    AND qs.status = 'completed'
                    AND qs.ended_at >= ?
                    GROUP BY qp.user_id
                ) ranked
                """,
                (guild_id, cutoff),
            )
            return int(row["total"]) if row else 0

        row = await self.db.fetchone(
            "SELECT COUNT(*) AS total FROM user_stats WHERE guild_id = ?",
            (guild_id,),
        )
        return int(row["total"]) if row else 0

    async def run_leaderboard_channel_updates(self, bot: discord.Client) -> None:
        for guild in bot.guilds:
            cfg = await self.get_guild_config(guild.id)
            if not cfg.leaderboard_channel_id:
                continue
            if cfg.leaderboard_update_minutes <= 0:
                continue

            channel = guild.get_channel(cfg.leaderboard_channel_id)
            if not isinstance(channel, discord.TextChannel):
                continue

            entries = await self.get_leaderboard(
                guild.id,
                "overall",
                limit=10,
                offset=0,
                weekly=False,
            )
            lines: list[str] = []
            for entry in entries:
                member = guild.get_member(entry.user_id)
                name = member.display_name if member else f"User {entry.user_id}"
                lines.append(f"**{entry.rank}.** {name} - {entry.value} XP")

            embed = discord.Embed(
                title="Live Leaderboard",
                description="\n".join(lines) if lines else "No entries yet.",
                color=Theme.primary,
            )
            embed.set_footer(text=f"Auto-updates every {cfg.leaderboard_update_minutes}m")

            now = utc_now()
            message: discord.Message | None = None
            if cfg.leaderboard_message_id:
                try:
                    message = await channel.fetch_message(cfg.leaderboard_message_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    message = None

            if message is not None:
                baseline = message.edited_at or message.created_at
                age_seconds = (now - baseline).total_seconds()
                if age_seconds < (cfg.leaderboard_update_minutes * 60):
                    continue
                try:
                    await message.edit(embed=embed)
                except (discord.Forbidden, discord.HTTPException):
                    LOGGER.warning("Failed to edit leaderboard message for guild=%s", guild.id)
                    continue
            else:
                try:
                    created = await channel.send(embed=embed)
                except (discord.Forbidden, discord.HTTPException):
                    LOGGER.warning("Failed to send leaderboard message for guild=%s", guild.id)
                    continue
                await self.update_guild_config_field(guild.id, "leaderboard_message_id", created.id)

    async def _ensure_guild_config_exists(self, guild_id: int) -> None:
        defaults = self.config.defaults
        await self.db.execute(
            """
            INSERT OR IGNORE INTO guild_config (
                guild_id,
                daily_quiz_time,
                chat_xp_enabled,
                voice_xp_enabled,
                min_quiz_players,
                quiz_cooldown_minutes,
                leaderboard_update_minutes,
                voice_xp_interval_minutes,
                voice_xp_base,
                voice_xp_group_bonus,
                voice_group_bonus_threshold,
                chat_xp_min,
                chat_xp_max,
                chat_xp_cooldown_seconds,
                min_message_length,
                ignore_command_messages,
                allow_muted_voice,
                disallow_self_deafened,
                ignore_afk_channel,
                default_quiz_category,
                lobby_duration_seconds,
                questions_per_quiz,
                question_time_limit_seconds
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                defaults.daily_quiz_time,
                int(True),
                int(True),
                defaults.min_quiz_players,
                defaults.quiz_cooldown_minutes,
                5,
                defaults.voice_xp_interval_minutes,
                defaults.voice_xp_base,
                defaults.voice_xp_group_bonus,
                defaults.voice_group_bonus_threshold,
                defaults.chat_xp_min,
                defaults.chat_xp_max,
                defaults.chat_xp_cooldown_seconds,
                defaults.min_message_length,
                int(defaults.ignore_command_messages),
                int(defaults.allow_muted_voice),
                int(defaults.disallow_self_deafened),
                int(defaults.ignore_afk_channel),
                defaults.default_quiz_category,
                defaults.lobby_duration_seconds,
                defaults.questions_per_quiz,
                defaults.question_time_limit_seconds,
            ),
        )


    async def _ensure_user_stats_exists(self, guild_id: int, user_id: int) -> None:
        await self.db.execute(
            """
            INSERT OR IGNORE INTO user_stats (guild_id, user_id)
            VALUES (?, ?)
            """,
            (guild_id, user_id),
        )

    async def _handle_level_up(
        self, *, guild: discord.Guild | None, member: discord.Member | None, event: LevelUpEvent
    ) -> None:
        if guild is None:
            return
        if member is None:
            potential_member = guild.get_member(event.user_id)
            member = potential_member
        if member is None:
            return

        awarded_roles = await self._grant_level_roles(guild, member, event.new_level)
        event.awarded_roles.extend(awarded_roles)

        guild_cfg = await self.get_guild_config(guild.id)
        if guild_cfg.levelup_channel_id:
            channel = guild.get_channel(guild_cfg.levelup_channel_id)
            if isinstance(channel, discord.TextChannel):
                await self._send_levelup_embed(channel, member, event)

    async def _grant_level_roles(
        self, guild: discord.Guild, member: discord.Member, new_level: int
    ) -> list[int]:
        mappings = await self.get_level_roles(guild.id)
        if not mappings:
            return []

        awarded: list[int] = []
        current_role_ids = {role.id for role in member.roles}
        highest_title = ""

        for threshold, role_id, title in mappings:
            if new_level < threshold:
                continue
            role = guild.get_role(role_id)
            if not role:
                continue
            if role.id not in current_role_ids:
                try:
                    await member.add_roles(role, reason=f"Reached level {new_level}")
                    awarded.append(role.id)
                except discord.Forbidden:
                    LOGGER.warning(
                        "Missing permission to add role %s in guild %s", role.id, guild.id
                    )
                except discord.HTTPException:
                    LOGGER.exception("Failed adding role %s in guild %s", role.id, guild.id)
            if title:
                highest_title = title

        if highest_title:
            await self.db.execute(
                """
                UPDATE user_stats
                SET title_label = ?
                WHERE guild_id = ? AND user_id = ?
                """,
                (highest_title, guild.id, member.id),
            )

        return awarded

    async def _send_levelup_embed(
        self, channel: discord.TextChannel, member: discord.Member, event: LevelUpEvent
    ) -> None:
        funny_lines = [
            "XP printer goes brrrr.",
            "Certified menace unlocked a new tier.",
            "Main character energy detected.",
            "Keep farming memories, not spam.",
            "That grind was suspiciously efficient.",
        ]
        embed = discord.Embed(
            title="Level Up!",
            description=f"{member.mention} just reached **Level {event.new_level}**",
            color=Theme.levelup,
        )
        embed.add_field(name="From", value=f"Lv {event.old_level}", inline=True)
        embed.add_field(name="To", value=f"Lv {event.new_level}", inline=True)
        embed.add_field(name="Flavor", value=random.choice(funny_lines), inline=False)
        if event.awarded_roles:
            roles_text = ", ".join(f"<@&{rid}>" for rid in event.awarded_roles[:4])
            embed.add_field(name="Rewards", value=roles_text, inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            LOGGER.warning(
                "Missing send/embed permission for levelup channel %s", channel.id
            )
        except discord.HTTPException:
            LOGGER.exception("Failed to send level-up message in channel %s", channel.id)

    def _looks_like_command(self, content: str) -> bool:
        stripped = content.strip()
        if not stripped:
            return False
        if stripped.startswith("/"):
            return True
        return stripped.startswith(self.config.default_prefix)

    def _is_repeated_spam(self, key: tuple[int, int], content: str, now: datetime) -> bool:
        normalized = normalize_for_spam_check(content)
        history = self._recent_messages[key]
        similar_recent = 0

        for old_text, old_time in list(history):
            if (now - old_time).total_seconds() > 600:
                continue
            if old_text == normalized:
                similar_recent += 1

        history.append((normalized, now))
        return similar_recent >= 2

    def _metric_to_column(self, metric: str) -> str:
        mapping = {
            "overall": "total_xp",
            "voice": "voice_xp",
            "quiz": "quiz_xp",
        }
        if metric not in mapping:
            raise ValueError(f"Unsupported leaderboard metric: {metric}")
        return mapping[metric]

    async def _get_weekly_quiz_leaderboard(
        self, guild_id: int, *, limit: int, offset: int
    ) -> list[LeaderboardEntry]:
        cutoff = (utc_now() - timedelta(days=7)).isoformat()
        rows = await self.db.fetchall(
            """
            SELECT qp.user_id, SUM(qp.score) AS value, us.level AS level
            FROM quiz_participants qp
            INNER JOIN quiz_sessions qs ON qs.session_id = qp.session_id
            LEFT JOIN user_stats us ON us.guild_id = qs.guild_id AND us.user_id = qp.user_id
            WHERE qs.guild_id = ?
              AND qs.status = 'completed'
              AND qs.ended_at >= ?
            GROUP BY qp.user_id
            ORDER BY value DESC, qp.user_id ASC
            LIMIT ? OFFSET ?
            """,
            (guild_id, cutoff, limit, offset),
        )
        entries: list[LeaderboardEntry] = []
        for index, row in enumerate(rows, start=offset + 1):
            entries.append(
                LeaderboardEntry(
                    user_id=int(row["user_id"]),
                    value=int(row["value"] or 0),
                    level=int(row["level"]) if row["level"] is not None else None,
                    rank=index,
                )
            )
        return entries

    async def _get_weekly_quiz_rank_position(self, guild_id: int, user_id: int) -> int | None:
        cutoff = (utc_now() - timedelta(days=7)).isoformat()
        viewer_row = await self.db.fetchone(
            """
            SELECT SUM(qp.score) AS value
            FROM quiz_participants qp
            INNER JOIN quiz_sessions qs ON qs.session_id = qp.session_id
            WHERE qs.guild_id = ?
              AND qs.status = 'completed'
              AND qs.ended_at >= ?
              AND qp.user_id = ?
            """,
            (guild_id, cutoff, user_id),
        )
        if not viewer_row or viewer_row["value"] is None:
            return None

        viewer_value = int(viewer_row["value"])
        ahead_row = await self.db.fetchone(
            """
            SELECT COUNT(*) + 1 AS rank
            FROM (
                SELECT qp.user_id, SUM(qp.score) AS total_score
                FROM quiz_participants qp
                INNER JOIN quiz_sessions qs ON qs.session_id = qp.session_id
                WHERE qs.guild_id = ?
                  AND qs.status = 'completed'
                  AND qs.ended_at >= ?
                GROUP BY qp.user_id
            ) grouped
            WHERE grouped.total_score > ?
               OR (grouped.total_score = ? AND grouped.user_id < ?)
            """,
            (guild_id, cutoff, viewer_value, viewer_value, user_id),
        )
        return int(ahead_row["rank"]) if ahead_row else None
