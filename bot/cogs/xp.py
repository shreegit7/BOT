from __future__ import annotations

import logging

import discord
from discord.ext import commands, tasks

LOGGER = logging.getLogger(__name__)


class XPCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._voice_synced = False

    async def cog_load(self) -> None:
        if not self.voice_award_loop.is_running():
            self.voice_award_loop.start()

    def cog_unload(self) -> None:
        if self.voice_award_loop.is_running():
            self.voice_award_loop.cancel()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._voice_synced:
            return
        try:
            await self.bot.voice_service.sync_active_sessions(self.bot.guilds)
            self._voice_synced = True
        except Exception:  # noqa: BLE001
            LOGGER.exception("Failed to sync active voice sessions on ready.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        try:
            await self.bot.xp_service.process_message_xp(message)
        except Exception:  # noqa: BLE001
            LOGGER.exception("Failed processing chat XP for message_id=%s", message.id)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        try:
            await self.bot.voice_service.handle_voice_state_update(member, before, after)
        except Exception:  # noqa: BLE001
            LOGGER.exception("Failed voice_state_update handling for user=%s", member.id)

    @tasks.loop(seconds=60)
    async def voice_award_loop(self) -> None:
        if not self.bot.is_ready():
            return
        try:
            await self.bot.voice_service.process_voice_awards(self.bot)
        except Exception:  # noqa: BLE001
            LOGGER.exception("Voice XP loop failure.")

    @voice_award_loop.before_loop
    async def before_voice_loop(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(XPCog(bot))
