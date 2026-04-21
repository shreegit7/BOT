from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.formatting import Theme
from bot.utils.time import parse_hhmm


class AdminConfigCog(commands.GroupCog, name="config", description="Admin-only configuration"):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__()
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message("Use this command in a server.", ephemeral=True)
            return False
        perms = interaction.user.guild_permissions
        if perms.administrator or perms.manage_guild:
            return True
        await interaction.response.send_message(
            "You need Manage Server permission for `/config` commands.",
            ephemeral=True,
        )
        return False

    @app_commands.command(name="quiz_channel", description="Set channel used for daily quiz posts")
    async def quiz_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        await self.bot.xp_service.update_guild_config_field(
            interaction.guild.id,
            "quiz_channel_id",
            channel.id,
        )
        await interaction.response.send_message(
            embed=self._ok_embed("Quiz Channel Updated", f"Daily quizzes will post in {channel.mention}.")
        )

    @app_commands.command(name="levelup_channel", description="Set channel used for level-up announcements")
    async def levelup_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        await self.bot.xp_service.update_guild_config_field(
            interaction.guild.id,
            "levelup_channel_id",
            channel.id,
        )
        await interaction.response.send_message(
            embed=self._ok_embed(
                "Level-Up Channel Updated",
                f"Level-up messages will post in {channel.mention}.",
            )
        )

    @app_commands.command(
        name="leaderboard_channel",
        description="Set channel used for auto-updating leaderboard posts",
    )
    async def leaderboard_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        await self.bot.xp_service.update_guild_config_field(
            interaction.guild.id,
            "leaderboard_channel_id",
            channel.id,
        )
        await self.bot.xp_service.update_guild_config_field(
            interaction.guild.id,
            "leaderboard_message_id",
            None,
        )
        await interaction.response.send_message(
            embed=self._ok_embed(
                "Leaderboard Channel Updated",
                f"Live leaderboard will post in {channel.mention}.",
            )
        )

    @app_commands.command(
        name="set_leaderboard_interval",
        description="Set auto leaderboard refresh interval in minutes (0 = off)",
    )
    async def set_leaderboard_interval(
        self, interaction: discord.Interaction, minutes: app_commands.Range[int, 0, 60]
    ) -> None:
        await self.bot.xp_service.update_guild_config_field(
            interaction.guild.id,
            "leaderboard_update_minutes",
            int(minutes),
        )
        if minutes == 0:
            msg = "Auto leaderboard updates are now **OFF**."
        else:
            msg = f"Auto leaderboard will refresh every **{minutes} minute(s)**."
        await interaction.response.send_message(
            embed=self._ok_embed("Leaderboard Interval Updated", msg)
        )

    @app_commands.command(name="voice_xp", description="Enable or disable voice XP awards")
    async def voice_xp(self, interaction: discord.Interaction, on_off: bool) -> None:
        await self.bot.xp_service.update_guild_config_field(
            interaction.guild.id,
            "voice_xp_enabled",
            int(on_off),
        )
        await interaction.response.send_message(
            embed=self._ok_embed("Voice XP Updated", f"Voice XP is now **{'ON' if on_off else 'OFF'}**.")
        )

    @app_commands.command(
        name="set_voice_interval",
        description="Set voice tracking/award interval in minutes",
    )
    async def set_voice_interval(
        self, interaction: discord.Interaction, minutes: app_commands.Range[int, 1, 30]
    ) -> None:
        await self.bot.xp_service.update_guild_config_field(
            interaction.guild.id,
            "voice_xp_interval_minutes",
            int(minutes),
        )
        await interaction.response.send_message(
            embed=self._ok_embed(
                "Voice Interval Updated",
                f"Voice tracking interval set to **{minutes} minute(s)**.",
            )
        )

    @app_commands.command(name="chat_xp", description="Enable or disable chat XP awards")
    async def chat_xp(self, interaction: discord.Interaction, on_off: bool) -> None:
        await self.bot.xp_service.update_guild_config_field(
            interaction.guild.id,
            "chat_xp_enabled",
            int(on_off),
        )
        await interaction.response.send_message(
            embed=self._ok_embed("Chat XP Updated", f"Chat XP is now **{'ON' if on_off else 'OFF'}**.")
        )

    @app_commands.command(name="set_daily_quiz_time", description="Set daily quiz time as HH:MM (24h)")
    async def set_daily_quiz_time(self, interaction: discord.Interaction, hhmm: str) -> None:
        try:
            hour, minute = parse_hhmm(hhmm)
        except ValueError:
            await interaction.response.send_message(
                "Invalid time format. Use `HH:MM` in 24-hour format.",
                ephemeral=True,
            )
            return

        formatted = f"{hour:02}:{minute:02}"
        await self.bot.xp_service.update_guild_config_field(
            interaction.guild.id,
            "daily_quiz_time",
            formatted,
        )
        await interaction.response.send_message(
            embed=self._ok_embed("Daily Quiz Time Updated", f"Daily quiz time is now **{formatted}**.")
        )

    @app_commands.command(name="set_level_role", description="Set role reward for reaching a level")
    async def set_level_role(
        self,
        interaction: discord.Interaction,
        level: app_commands.Range[int, 1, 500],
        role: discord.Role,
        title_label: str | None = None,
    ) -> None:
        await self.bot.xp_service.set_level_role(
            interaction.guild.id,
            level_threshold=level,
            role_id=role.id,
            title_label=(title_label or "").strip(),
        )
        msg = f"Level **{level}** now grants {role.mention}."
        if title_label:
            msg += f" Title: **{title_label.strip()}**"
        await interaction.response.send_message(embed=self._ok_embed("Level Role Updated", msg))

    @app_commands.command(name="set_quiz_cooldown", description="Set on-demand quiz cooldown (minutes)")
    async def set_quiz_cooldown(
        self, interaction: discord.Interaction, minutes: app_commands.Range[int, 0, 240]
    ) -> None:
        await self.bot.xp_service.update_guild_config_field(
            interaction.guild.id,
            "quiz_cooldown_minutes",
            int(minutes),
        )
        if minutes == 0:
            message = "Cooldown is now **OFF**."
        else:
            message = f"Cooldown set to **{minutes} minutes**."
        await interaction.response.send_message(
            embed=self._ok_embed("Quiz Cooldown Updated", message)
        )

    @app_commands.command(
        name="quiz_cooldown",
        description="Quickly turn on/off on-demand quiz cooldown timer",
    )
    async def quiz_cooldown(self, interaction: discord.Interaction, on_off: bool) -> None:
        cfg = await self.bot.xp_service.get_guild_config(interaction.guild.id)
        if on_off:
            minutes = cfg.quiz_cooldown_minutes if cfg.quiz_cooldown_minutes > 0 else 10
            await self.bot.xp_service.update_guild_config_field(
                interaction.guild.id,
                "quiz_cooldown_minutes",
                int(minutes),
            )
            msg = f"Cooldown timer is now **ON** ({minutes} minutes)."
        else:
            await self.bot.xp_service.update_guild_config_field(
                interaction.guild.id,
                "quiz_cooldown_minutes",
                0,
            )
            msg = "Cooldown timer is now **OFF**."
        await interaction.response.send_message(
            embed=self._ok_embed("Quiz Cooldown Timer", msg)
        )

    @app_commands.command(name="set_min_players", description="Set minimum players required to reward quiz XP")
    async def set_min_players(
        self, interaction: discord.Interaction, count: app_commands.Range[int, 1, 20]
    ) -> None:
        await self.bot.xp_service.update_guild_config_field(
            interaction.guild.id,
            "min_quiz_players",
            int(count),
        )
        await interaction.response.send_message(
            embed=self._ok_embed("Min Players Updated", f"Quiz minimum players set to **{count}**.")
        )

    def _ok_embed(self, title: str, description: str) -> discord.Embed:
        return discord.Embed(title=title, description=description, color=Theme.success)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminConfigCog(bot))
