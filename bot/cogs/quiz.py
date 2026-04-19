from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.utils.formatting import Theme

LOGGER = logging.getLogger(__name__)


class QuizCog(commands.GroupCog, name="quiz", description="Multiplayer quiz commands"):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__()
        self.bot = bot

    async def cog_load(self) -> None:
        if not self.daily_scheduler_loop.is_running():
            self.daily_scheduler_loop.start()

    def cog_unload(self) -> None:
        if self.daily_scheduler_loop.is_running():
            self.daily_scheduler_loop.cancel()

    @app_commands.command(name="start", description="Start a quiz lobby with category and question count")
    @app_commands.choices(
        category=[
            app_commands.Choice(name="random", value="random"),
            app_commands.Choice(name="artliterature", value="artliterature"),
            app_commands.Choice(name="language", value="language"),
            app_commands.Choice(name="sciencenature", value="sciencenature"),
            app_commands.Choice(name="general", value="general"),
            app_commands.Choice(name="fooddrink", value="fooddrink"),
            app_commands.Choice(name="peopleplaces", value="peopleplaces"),
            app_commands.Choice(name="geography", value="geography"),
            app_commands.Choice(name="historyholidays", value="historyholidays"),
            app_commands.Choice(name="entertainment", value="entertainment"),
            app_commands.Choice(name="toysgames", value="toysgames"),
            app_commands.Choice(name="music", value="music"),
            app_commands.Choice(name="mathematics", value="mathematics"),
            app_commands.Choice(name="religionmythology", value="religionmythology"),
            app_commands.Choice(name="sportsleisure", value="sportsleisure"),
        ],
        questions=[
            app_commands.Choice(name="5", value=5),
            app_commands.Choice(name="10", value=10),
        ],
        difficulty=[
            app_commands.Choice(name="easy", value="easy"),
            app_commands.Choice(name="medium", value="medium"),
            app_commands.Choice(name="hard", value="hard"),
        ],
    )
    async def start(
        self,
        interaction: discord.Interaction,
        category: app_commands.Choice[str] | None = None,
        questions: app_commands.Choice[int] | None = None,
        difficulty: app_commands.Choice[str] | None = None,
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Use this in a server text channel.", ephemeral=True)
            return

        selected_category = category.value if category else None
        selected_questions = questions.value if questions else None
        selected_difficulty = difficulty.value if difficulty else "medium"

        success, message = await self.bot.quiz_service.start_lobby(
            guild=interaction.guild,
            channel=interaction.channel,
            host_user_id=interaction.user.id,
            quiz_type="ondemand",
            category=selected_category,
            difficulty=selected_difficulty,
            question_count=selected_questions,
        )
        embed = discord.Embed(
            title="Quiz Lobby",
            description=message,
            color=Theme.success if success else Theme.warning,
        )
        await interaction.response.send_message(embed=embed, ephemeral=not success)

    @app_commands.command(name="join", description="Join current quiz lobby")
    async def join(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Use this in a server.", ephemeral=True)
            return
        success, message = await self.bot.quiz_service.join_lobby(
            interaction.guild.id, interaction.user.id
        )
        await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(name="leave", description="Leave current quiz lobby")
    async def leave(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Use this in a server.", ephemeral=True)
            return
        success, message = await self.bot.quiz_service.leave_lobby(
            interaction.guild.id, interaction.user.id
        )
        await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(name="category", description="Set default quiz category for this server")
    @app_commands.choices(
        category=[
            app_commands.Choice(name="general", value="general"),
            app_commands.Choice(name="artliterature", value="artliterature"),
            app_commands.Choice(name="language", value="language"),
            app_commands.Choice(name="sciencenature", value="sciencenature"),
            app_commands.Choice(name="fooddrink", value="fooddrink"),
            app_commands.Choice(name="peopleplaces", value="peopleplaces"),
            app_commands.Choice(name="geography", value="geography"),
            app_commands.Choice(name="historyholidays", value="historyholidays"),
            app_commands.Choice(name="entertainment", value="entertainment"),
            app_commands.Choice(name="toysgames", value="toysgames"),
            app_commands.Choice(name="music", value="music"),
            app_commands.Choice(name="mathematics", value="mathematics"),
            app_commands.Choice(name="religionmythology", value="religionmythology"),
            app_commands.Choice(name="sportsleisure", value="sportsleisure"),
        ]
    )
    async def category(self, interaction: discord.Interaction, category: app_commands.Choice[str]) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Use this in a server.", ephemeral=True)
            return
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "Manage Server permission is required for this setting.",
                ephemeral=True,
            )
            return

        await self.bot.xp_service.update_guild_config_field(
            interaction.guild.id,
            "default_quiz_category",
            category.value,
        )
        embed = discord.Embed(
            title="Default Category Updated",
            description=f"Default quiz category is now **{category.value}**.",
            color=Theme.success,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="cancel", description="Cancel active quiz")
    async def cancel(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Use this in a server.", ephemeral=True)
            return
        member = interaction.guild.get_member(interaction.user.id)
        if member is None:
            await interaction.response.send_message("Member not found.", ephemeral=True)
            return
        success, message = await self.bot.quiz_service.cancel_quiz(interaction.guild.id, member)
        await interaction.response.send_message(message, ephemeral=True)

    @tasks.loop(seconds=30)
    async def daily_scheduler_loop(self) -> None:
        if not self.bot.is_ready():
            return
        try:
            await self.bot.quiz_service.run_daily_scheduler_tick()
        except Exception:  # noqa: BLE001
            LOGGER.exception("Daily quiz scheduler tick failed.")

    @daily_scheduler_loop.before_loop
    async def before_daily_loop(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(QuizCog(bot))
