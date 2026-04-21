from __future__ import annotations

import logging
from datetime import datetime, timedelta

import discord

from bot.services.xp_service import XPService
from bot.utils.time import utc_now

LOGGER = logging.getLogger(__name__)


class VoiceService:
    def __init__(self, xp_service: XPService) -> None:
        self.xp_service = xp_service

    async def handle_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot:
            return

        now_iso = utc_now().isoformat()
        guild_id = member.guild.id
        user_id = member.id

        if before.channel and after.channel and before.channel.id == after.channel.id:
            return

        if after.channel is None:
            await self._deactivate_session(guild_id, user_id)
            return

        await self.xp_service.db.execute(
            """
            INSERT INTO voice_sessions (guild_id, user_id, channel_id, joined_at, last_checked_at, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
            ON CONFLICT(guild_id, user_id)
            DO UPDATE SET
                channel_id = excluded.channel_id,
                joined_at = excluded.joined_at,
                last_checked_at = excluded.last_checked_at,
                is_active = 1
            """,
            (guild_id, user_id, after.channel.id, now_iso, now_iso),
        )

    async def sync_active_sessions(self, guilds: list[discord.Guild]) -> None:
        now_iso = utc_now().isoformat()
        await self.xp_service.db.execute("UPDATE voice_sessions SET is_active = 0")

        rows: list[tuple[int, int, int, str, str, int]] = []
        for guild in guilds:
            for channel in guild.voice_channels:
                for member in channel.members:
                    if member.bot:
                        continue
                    rows.append((guild.id, member.id, channel.id, now_iso, now_iso, 1))

        if rows:
            await self.xp_service.db.executemany(
                """
                INSERT INTO voice_sessions (guild_id, user_id, channel_id, joined_at, last_checked_at, is_active)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id)
                DO UPDATE SET
                    channel_id = excluded.channel_id,
                    joined_at = excluded.joined_at,
                    last_checked_at = excluded.last_checked_at,
                    is_active = excluded.is_active
                """,
                rows,
            )

    async def process_voice_awards(self, bot: discord.Client) -> None:
        rows = await self.xp_service.db.fetchall(
            """
            SELECT guild_id, user_id, channel_id, last_checked_at
            FROM voice_sessions
            WHERE is_active = 1
            """
        )
        if not rows:
            return

        for row in rows:
            guild_id = int(row["guild_id"])
            user_id = int(row["user_id"])
            guild = bot.get_guild(guild_id)
            if not guild:
                await self._deactivate_session(guild_id, user_id)
                continue

            member = guild.get_member(user_id)
            if member is None or member.bot:
                await self._deactivate_session(guild_id, user_id)
                continue

            cfg = await self.xp_service.get_guild_config(guild_id)
            if not cfg.voice_xp_enabled:
                await self._set_last_checked(guild_id, user_id, utc_now())
                continue

            if member.voice is None or member.voice.channel is None:
                await self._deactivate_session(guild_id, user_id)
                continue

            if cfg.ignore_afk_channel and guild.afk_channel and member.voice.channel.id == guild.afk_channel.id:
                await self._set_last_checked(guild_id, user_id, utc_now())
                continue

            if not cfg.allow_muted_voice and member.voice.self_mute:
                await self._set_last_checked(guild_id, user_id, utc_now())
                continue

            if cfg.disallow_self_deafened and member.voice.self_deaf:
                await self._set_last_checked(guild_id, user_id, utc_now())
                continue

            try:
                last_checked = datetime.fromisoformat(str(row["last_checked_at"]))
            except ValueError:
                last_checked = utc_now()

            now = utc_now()
            interval_seconds = max(60, cfg.voice_xp_interval_minutes * 60)
            elapsed_seconds = int((now - last_checked).total_seconds())
            if elapsed_seconds < interval_seconds:
                continue

            intervals = min(3, elapsed_seconds // interval_seconds)
            processed_intervals = 0
            for _ in range(intervals):
                if not self._is_eligible_channel_state(member, cfg):
                    break

                # Track voice time for valid presence, even if XP conditions are not met.
                await self.xp_service.add_voice_minutes(
                    guild_id=guild_id,
                    user_id=user_id,
                    minutes=cfg.voice_xp_interval_minutes,
                )
                processed_intervals += 1

                humans = [
                    m
                    for m in member.voice.channel.members
                    if not m.bot and m.id != member.id
                ]
                if len(humans) < 1:
                    continue

                group_size = len(humans) + 1
                xp_amount = (
                    cfg.voice_xp_group_bonus
                    if group_size >= cfg.voice_group_bonus_threshold
                    else cfg.voice_xp_base
                )
                await self.xp_service.add_xp(
                    guild_id=guild_id,
                    user_id=user_id,
                    amount=xp_amount,
                    xp_type="voice_xp",
                    guild=guild,
                    member=member,
                    allow_levelup_announce=True,
                )

            if processed_intervals > 0:
                updated = last_checked + timedelta(seconds=interval_seconds * processed_intervals)
            else:
                updated = now
            await self._set_last_checked(guild_id, user_id, updated)

    def _is_eligible_channel_state(self, member: discord.Member, cfg: object) -> bool:
        if member.voice is None or member.voice.channel is None:
            return False
        if getattr(cfg, "disallow_self_deafened", True) and member.voice.self_deaf:
            return False
        if not getattr(cfg, "allow_muted_voice", True) and member.voice.self_mute:
            return False
        return True

    async def _set_last_checked(self, guild_id: int, user_id: int, dt: datetime) -> None:
        await self.xp_service.db.execute(
            """
            UPDATE voice_sessions
            SET last_checked_at = ?
            WHERE guild_id = ? AND user_id = ?
            """,
            (dt.isoformat(), guild_id, user_id),
        )

    async def _deactivate_session(self, guild_id: int, user_id: int) -> None:
        await self.xp_service.db.execute(
            """
            UPDATE voice_sessions
            SET is_active = 0, channel_id = NULL
            WHERE guild_id = ? AND user_id = ?
            """,
            (guild_id, user_id),
        )
