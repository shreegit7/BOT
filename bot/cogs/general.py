from __future__ import annotations

import logging
import math
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from bot.models import LeaderboardEntry, UserStats
from bot.utils.formatting import Theme, compact_number, progress_bar
from bot.utils.leaderboard_card import LeaderboardCardRow, render_leaderboard_card
from bot.utils.levels import progress_in_level
from bot.utils.rank_card import render_rank_card
from bot.utils.time import format_minutes

LOGGER = logging.getLogger(__name__)


class LeaderboardPaginationView(discord.ui.View):
    def __init__(
        self,
        *,
        cog: "GeneralCog",
        guild_id: int,
        metric: str,
        weekly: bool,
        viewer_rank: int | None,
        total_pages: int,
    ) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.guild_id = guild_id
        self.metric = metric
        self.weekly = weekly
        self.viewer_rank = viewer_rank
        self.total_pages = max(1, total_pages)
        self.page = 1
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        self.prev_button.disabled = self.page <= 1
        self.next_button.disabled = self.page >= self.total_pages

    async def _render_page(self) -> discord.Embed:
        if self.metric == "stats":
            entries = await self.cog.bot.xp_service.get_stats_leaderboard(
                self.guild_id,
                limit=10,
                offset=(self.page - 1) * 10,
            )
        else:
            entries = await self.cog.bot.xp_service.get_leaderboard(
                self.guild_id,
                self.metric,
                limit=10,
                offset=(self.page - 1) * 10,
                weekly=self.weekly,
            )
        guild = self.cog.bot.get_guild(self.guild_id)
        return self.cog.build_leaderboard_embed(
            guild=guild,
            metric=self.metric,
            weekly=self.weekly,
            entries=entries,
            page=self.page,
            total_pages=self.total_pages,
            viewer_rank=self.viewer_rank,
        )

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.secondary)
    async def prev_button(
        self, interaction: discord.Interaction, _: discord.ui.Button["LeaderboardPaginationView"]
    ) -> None:
        if self.page <= 1:
            await interaction.response.defer()
            return
        self.page -= 1
        self._refresh_buttons()
        embed = await self._render_page()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_button(
        self, interaction: discord.Interaction, _: discord.ui.Button["LeaderboardPaginationView"]
    ) -> None:
        if self.page >= self.total_pages:
            await interaction.response.defer()
            return
        self.page += 1
        self._refresh_buttons()
        embed = await self._render_page()
        await interaction.response.edit_message(embed=embed, view=self)


class GeneralCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="rank", description="Show your rank card or another user's rank card")
    @app_commands.describe(user="Optional: check someone else's rank")
    async def rank(
        self, interaction: discord.Interaction, user: discord.Member | None = None
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Use this command in a server.", ephemeral=True)
            return

        target = user or interaction.user
        if not isinstance(target, discord.Member):
            await interaction.response.send_message("User not found in this server.", ephemeral=True)
            return

        await interaction.response.defer()
        stats = await self.bot.xp_service.get_user_stats(interaction.guild.id, target.id)
        rank_position = await self.bot.xp_service.get_rank_position(
            interaction.guild.id, target.id, metric="overall"
        )
        if rank_position is None:
            rank_position = 1
        level, gained, needed, ratio = progress_in_level(stats.total_xp)

        embed = self._build_rank_embed(target, stats, rank_position, ratio, gained, needed)
        try:
            card = await render_rank_card(
                member=target,
                level=level,
                total_xp=stats.total_xp,
                rank_position=rank_position,
                progress_ratio=ratio,
                level_xp_gained=gained,
                level_xp_needed=needed,
                chat_xp=stats.chat_xp,
                voice_xp=stats.voice_xp,
                quiz_xp=stats.quiz_xp,
                voice_minutes=stats.total_voice_minutes,
                title_label=stats.title_label,
            )
            file = discord.File(card, filename="rank_card.png")
            embed.set_image(url="attachment://rank_card.png")
            await interaction.followup.send(embed=embed, file=file)
        except Exception:  # noqa: BLE001
            LOGGER.exception("Rank card rendering failed for user=%s", target.id)
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="profile", description="Show compact stats breakdown")
    @app_commands.describe(user="Optional: check someone else's profile")
    async def profile(
        self, interaction: discord.Interaction, user: discord.Member | None = None
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Use this command in a server.", ephemeral=True)
            return
        target = user or interaction.user
        if not isinstance(target, discord.Member):
            await interaction.response.send_message("User not found in this server.", ephemeral=True)
            return

        stats = await self.bot.xp_service.get_user_stats(interaction.guild.id, target.id)
        rank_position = await self.bot.xp_service.get_rank_position(
            interaction.guild.id, target.id, metric="overall"
        )
        level, gained, needed, ratio = progress_in_level(stats.total_xp)

        embed = discord.Embed(
            title=f"{target.display_name} - Profile",
            color=Theme.primary,
            description=(
                f"Level **{level}** | Rank **#{rank_position or '-'}**\n"
                f"{progress_bar(ratio)} `{gained}/{needed}`"
            ),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Total XP", value=compact_number(stats.total_xp), inline=True)
        embed.add_field(name="Messages", value=compact_number(stats.messages_count), inline=True)
        embed.add_field(name="Voice Time", value=format_minutes(stats.total_voice_minutes), inline=True)
        embed.add_field(name="Chat XP", value=compact_number(stats.chat_xp), inline=True)
        embed.add_field(name="Voice XP", value=compact_number(stats.voice_xp), inline=True)
        embed.add_field(name="Quiz XP", value=compact_number(stats.quiz_xp), inline=True)
        embed.add_field(name="Quiz Wins", value=compact_number(stats.quiz_wins), inline=True)
        embed.add_field(name="Correct Answers", value=compact_number(stats.correct_answers), inline=True)
        embed.add_field(name="Daily Streak", value=str(stats.daily_quiz_streak), inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leaderboard", description="Show leaderboard by overall, voice, or quiz")
    @app_commands.choices(
        metric=[
            app_commands.Choice(name="overall", value="overall"),
            app_commands.Choice(name="voice", value="voice"),
            app_commands.Choice(name="quiz", value="quiz"),
            app_commands.Choice(name="stats", value="stats"),
        ],
        timeframe=[
            app_commands.Choice(name="all-time", value="all_time"),
            app_commands.Choice(name="weekly", value="weekly"),
        ],
    )
    async def leaderboard(
        self,
        interaction: discord.Interaction,
        metric: app_commands.Choice[str],
        timeframe: app_commands.Choice[str] | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Use this command in a server.", ephemeral=True)
            return

        tf = timeframe.value if timeframe else "all_time"
        weekly = tf == "weekly"
        metric_value = metric.value
        if weekly and metric_value != "quiz":
            await interaction.response.send_message(
                "Weekly mode is currently available only for quiz leaderboard.",
                ephemeral=True,
            )
            return

        total_users = await self.bot.xp_service.count_users_for_metric(
            interaction.guild.id,
            "overall" if metric_value == "stats" else metric_value,
            weekly=weekly and metric_value == "quiz",
        )
        total_pages = max(1, math.ceil(total_users / 10)) if total_users else 1
        viewer_rank = await self.bot.xp_service.get_rank_position(
            interaction.guild.id,
            interaction.user.id,
            metric="overall" if metric_value == "stats" else metric_value,
            weekly=weekly and metric_value == "quiz",
        )
        if metric_value == "stats":
            entries = await self.bot.xp_service.get_stats_leaderboard(
                interaction.guild.id,
                limit=10,
                offset=0,
            )
        else:
            entries = await self.bot.xp_service.get_leaderboard(
                interaction.guild.id,
                metric_value,
                limit=10,
                offset=0,
                weekly=weekly,
            )

        embed = self.build_leaderboard_embed(
            guild=interaction.guild,
            metric=metric_value,
            weekly=weekly,
            entries=entries,
            page=1,
            total_pages=total_pages,
            viewer_rank=viewer_rank,
        )
        file: discord.File | None = None
        try:
            card_rows = self._build_leaderboard_card_rows(
                guild=interaction.guild,
                metric=metric_value,
                entries=entries,
                page=1,
            )
            card_title = self._leaderboard_title(metric_value, weekly)
            subtitle = f"Top players in {interaction.guild.name}"
            card = await render_leaderboard_card(
                title=card_title,
                subtitle=subtitle,
                rows=card_rows,
            )
            file = discord.File(card, filename="leaderboard_card.png")
            embed.set_image(url="attachment://leaderboard_card.png")
        except Exception:  # noqa: BLE001
            LOGGER.exception("Leaderboard card rendering failed for guild=%s", interaction.guild.id)

        if total_pages <= 1:
            if file:
                await interaction.response.send_message(embed=embed, file=file)
            else:
                await interaction.response.send_message(embed=embed)
            return

        view = LeaderboardPaginationView(
            cog=self,
            guild_id=interaction.guild.id,
            metric=metric_value,
            weekly=weekly,
            viewer_rank=viewer_rank,
            total_pages=total_pages,
        )
        if file:
            await interaction.response.send_message(embed=embed, file=file, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="dailyquiz", description="Show today's daily quiz info or join if active")
    @app_commands.describe(join="Set to true to join the active daily quiz lobby")
    async def dailyquiz(self, interaction: discord.Interaction, join: bool = False) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Use this command in a server.", ephemeral=True)
            return

        if join:
            success, message = await self.bot.quiz_service.join_active_daily_lobby(
                interaction.guild.id, interaction.user.id
            )
            await interaction.response.send_message(
                message,
                ephemeral=True,
            )
            return

        info = await self.bot.quiz_service.get_daily_info(interaction.guild.id)
        seconds_until = int(info["seconds_until_next"])
        next_text = str(timedelta(seconds=seconds_until))
        active_session = info["active_lobby"]

        embed = discord.Embed(title="Daily Quiz", color=Theme.quiz)
        embed.add_field(name="Scheduled Time", value=str(info["scheduled_time"]), inline=True)
        embed.add_field(name="Starts In", value=next_text, inline=True)
        if active_session:
            embed.add_field(
                name="Lobby Status",
                value=(
                    f"Live now in <#{active_session.channel_id}> with "
                    f"**{len(active_session.participants)}** players.\n"
                    "Use `/dailyquiz join:true` to join."
                ),
                inline=False,
            )
        else:
            embed.add_field(
                name="Lobby Status",
                value="No active daily lobby right now.",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    def build_leaderboard_embed(
        self,
        *,
        guild: discord.Guild | None,
        metric: str,
        weekly: bool,
        entries: list[object],
        page: int,
        total_pages: int,
        viewer_rank: int | None,
    ) -> discord.Embed:
        metric_label = {
            "overall": "Overall XP",
            "voice": "Voice XP",
            "quiz": "Quiz XP" if not weekly else "Weekly Quiz Points",
            "stats": "Server Stats",
        }[metric]
        title = f"{metric_label} Leaderboard"
        if weekly:
            title = "Weekly Quiz Leaderboard"

        lines: list[str] = []
        if metric == "stats":
            for index, raw in enumerate(entries, start=((page - 1) * 10) + 1):
                if not isinstance(raw, dict):
                    continue
                user_id = int(raw.get("user_id", 0))
                if guild:
                    member = guild.get_member(user_id)
                    name = member.display_name if member else f"User {user_id}"
                else:
                    name = f"User {user_id}"
                lines.append(
                    (
                        f"**{index}. {name}** | Lv {int(raw.get('level', 0))} | "
                        f"XP {compact_number(int(raw.get('total_xp', 0)))}\n"
                        f"Chat {compact_number(int(raw.get('chat_xp', 0)))} | "
                        f"Voice {compact_number(int(raw.get('voice_xp', 0)))} | "
                        f"Quiz {compact_number(int(raw.get('quiz_xp', 0)))} | "
                        f"Voice Time {format_minutes(int(raw.get('total_voice_minutes', 0)))} | "
                        f"Wins {compact_number(int(raw.get('quiz_wins', 0)))}"
                    )
                )
        else:
            for raw in entries:
                if not isinstance(raw, LeaderboardEntry):
                    continue
                if guild:
                    member = guild.get_member(raw.user_id)
                    name = member.display_name if member else f"User {raw.user_id}"
                else:
                    name = f"User {raw.user_id}"
                lines.append(f"**{raw.rank}.** {name} - {compact_number(raw.value)}")

        embed = discord.Embed(
            title=title,
            description="\n\n".join(lines) if lines else "No entries yet.",
            color=Theme.primary,
        )
        embed.set_footer(text=f"Page {page}/{total_pages}")
        if viewer_rank is not None and viewer_rank > 10 * page:
            embed.add_field(name="Your Position", value=f"#{viewer_rank}", inline=False)
        elif viewer_rank is not None:
            embed.add_field(name="Your Position", value=f"#{viewer_rank}", inline=False)
        return embed

    def _build_rank_embed(
        self,
        member: discord.Member,
        stats: UserStats,
        rank_position: int,
        ratio: float,
        gained: int,
        needed: int,
    ) -> discord.Embed:
        embed = discord.Embed(
            title=f"{member.display_name} - Rank Card",
            color=Theme.primary,
            description=f"{progress_bar(ratio)} `{gained}/{needed}` to next level",
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Rank", value=f"#{rank_position}", inline=True)
        embed.add_field(name="Level", value=str(stats.level), inline=True)
        embed.add_field(name="Total XP", value=compact_number(stats.total_xp), inline=True)
        embed.add_field(name="Chat XP", value=compact_number(stats.chat_xp), inline=True)
        embed.add_field(name="Voice XP", value=compact_number(stats.voice_xp), inline=True)
        embed.add_field(name="Quiz XP", value=compact_number(stats.quiz_xp), inline=True)
        embed.add_field(name="Voice Time", value=format_minutes(stats.total_voice_minutes), inline=True)
        if stats.title_label:
            embed.add_field(name="Title", value=stats.title_label, inline=True)
        return embed

    def _leaderboard_title(self, metric: str, weekly: bool) -> str:
        if weekly and metric == "quiz":
            return "Weekly Quiz Leaderboard"
        return {
            "overall": "Overall XP Leaderboard",
            "voice": "Voice XP Leaderboard",
            "quiz": "Quiz XP Leaderboard",
            "stats": "Server Stats Leaderboard",
        }.get(metric, "Leaderboard")

    def _build_leaderboard_card_rows(
        self,
        *,
        guild: discord.Guild | None,
        metric: str,
        entries: list[object],
        page: int,
    ) -> list[LeaderboardCardRow]:
        rows: list[LeaderboardCardRow] = []
        if metric == "stats":
            for index, raw in enumerate(entries, start=((page - 1) * 10) + 1):
                if not isinstance(raw, dict):
                    continue
                user_id = int(raw.get("user_id", 0))
                member = guild.get_member(user_id) if guild else None
                name = member.display_name if member else f"User {user_id}"
                primary = (
                    f"Lv {int(raw.get('level', 0))} | Total XP {compact_number(int(raw.get('total_xp', 0)))}"
                )
                secondary = (
                    f"C {compact_number(int(raw.get('chat_xp', 0)))} "
                    f"V {compact_number(int(raw.get('voice_xp', 0)))} "
                    f"Q {compact_number(int(raw.get('quiz_xp', 0)))} "
                    f"W {compact_number(int(raw.get('quiz_wins', 0)))}"
                )
                rows.append(
                    LeaderboardCardRow(
                        rank=index,
                        name=name,
                        primary=primary,
                        secondary=secondary,
                    )
                )
            return rows

        for raw in entries:
            if not isinstance(raw, LeaderboardEntry):
                continue
            member = guild.get_member(raw.user_id) if guild else None
            name = member.display_name if member else f"User {raw.user_id}"
            rows.append(
                LeaderboardCardRow(
                    rank=raw.rank,
                    name=name,
                    primary=compact_number(raw.value),
                    secondary=f"Level {raw.level or 0}",
                )
            )
        return rows


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GeneralCog(bot))

