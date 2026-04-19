from __future__ import annotations

import asyncio
import logging
import secrets
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import discord

from bot.config import AppConfig
from bot.models import AnswerRecord, QuizPlayerState, TriviaQuestion
from bot.services.trivia_api import SUPPORTED_CATEGORIES, TriviaAPI
from bot.services.xp_service import XPService
from bot.utils.formatting import Theme, short_display
from bot.utils.time import now_in_timezone, seconds_until_next_time, utc_now
from bot.views.quiz_views import LobbyView, QuizAnswerView

LOGGER = logging.getLogger(__name__)

QUIZ_POINTS_CORRECT = 100
QUIZ_POINTS_SPEED_CAP = 40


@dataclass(slots=True)
class RuntimeQuizSession:
    session_id: str
    guild_id: int
    channel_id: int
    host_user_id: int
    quiz_type: str
    category: str
    difficulty: str
    question_count: int
    created_at: datetime
    participants: set[int] = field(default_factory=set)
    players: dict[int, QuizPlayerState] = field(default_factory=dict)
    status: str = "lobby"
    questions: list[TriviaQuestion] = field(default_factory=list)
    current_question_index: int = -1
    question_started_at: datetime | None = None
    answers_by_question: dict[int, dict[int, AnswerRecord]] = field(default_factory=dict)
    lobby_message: discord.Message | None = None
    answer_view: QuizAnswerView | None = None
    lobby_view: LobbyView | None = None
    lobby_task: asyncio.Task[None] | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class QuizService:
    def __init__(
        self,
        *,
        bot: discord.Client,
        xp_service: XPService,
        trivia_api: TriviaAPI,
        config: AppConfig,
    ) -> None:
        self.bot = bot
        self.xp_service = xp_service
        self.trivia_api = trivia_api
        self.config = config

        self._active_by_guild: dict[int, RuntimeQuizSession] = {}
        self._by_session_id: dict[str, RuntimeQuizSession] = {}
        self._button_rate_limiter: dict[tuple[int, int], datetime] = {}
        self._recent_questions_by_guild: dict[int, deque[str]] = defaultdict(
            lambda: deque(maxlen=250)
        )
        self._service_lock = asyncio.Lock()

    def get_supported_categories(self) -> list[str]:
        return SUPPORTED_CATEGORIES

    def get_active_session(self, guild_id: int) -> RuntimeQuizSession | None:
        return self._active_by_guild.get(guild_id)

    def get_active_daily_lobby(self, guild_id: int) -> RuntimeQuizSession | None:
        session = self.get_active_session(guild_id)
        if session and session.quiz_type == "daily" and session.status == "lobby":
            return session
        return None

    async def start_lobby(
        self,
        *,
        guild: discord.Guild,
        channel: discord.TextChannel,
        host_user_id: int,
        quiz_type: str = "ondemand",
        category: str | None = None,
        difficulty: str | None = None,
        question_count: int | None = None,
    ) -> tuple[bool, str]:
        async with self._service_lock:
            active = self._active_by_guild.get(guild.id)
            if active:
                return False, "A quiz is already active in this server."

            cfg = await self.xp_service.get_guild_config(guild.id)
            if quiz_type == "ondemand":
                remaining = await self._ondemand_cooldown_remaining(
                    guild.id, cfg.quiz_cooldown_minutes
                )
                if remaining > 0:
                    return False, f"Quiz cooldown active. Try again in {remaining // 60 + 1}m."

            picked_category = self._resolve_category(category, cfg.default_quiz_category)
            picked_difficulty = self._resolve_difficulty(difficulty)
            picked_questions = question_count or cfg.questions_per_quiz
            if picked_questions not in {5, 10}:
                picked_questions = 5 if picked_questions < 8 else 10

            now = utc_now()
            session = RuntimeQuizSession(
                session_id=f"{guild.id}-{secrets.token_hex(4)}",
                guild_id=guild.id,
                channel_id=channel.id,
                host_user_id=host_user_id,
                quiz_type=quiz_type,
                category=picked_category,
                difficulty=picked_difficulty,
                question_count=picked_questions,
                created_at=now,
            )

            host_member = guild.get_member(host_user_id)
            if host_member and not host_member.bot:
                session.participants.add(host_user_id)
                session.players[host_user_id] = QuizPlayerState(user_id=host_user_id)

            await self.xp_service.db.execute(
                """
                INSERT INTO quiz_sessions (
                    session_id, guild_id, channel_id, host_user_id, quiz_type, category,
                    question_count, started_at, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.session_id,
                    session.guild_id,
                    session.channel_id,
                    session.host_user_id,
                    session.quiz_type,
                    session.category,
                    session.question_count,
                    now.isoformat(),
                    "lobby",
                ),
            )

            self._active_by_guild[guild.id] = session
            self._by_session_id[session.session_id] = session

            lobby_timeout = max(15, cfg.lobby_duration_seconds)
            session.lobby_view = LobbyView(
                timeout=float(lobby_timeout),
                on_join=lambda interaction: self.join_lobby(guild.id, interaction.user.id),
                on_leave=lambda interaction: self.leave_lobby(guild.id, interaction.user.id),
                on_start=lambda interaction: self._start_now_from_button(interaction, guild.id),
                on_cancel=lambda interaction: self._cancel_from_button(interaction, guild.id),
            )

            session.lobby_message = await channel.send(
                embed=self._build_lobby_embed(guild, session, cfg),
                view=session.lobby_view,
            )
            session.lobby_task = asyncio.create_task(
                self._auto_start_after_delay(guild.id, lobby_timeout),
                name=f"quiz-lobby-{session.session_id}",
            )
            return True, "Quiz lobby opened."

    async def join_lobby(self, guild_id: int, user_id: int) -> tuple[bool, str]:
        session = self._active_by_guild.get(guild_id)
        if not session or session.status != "lobby":
            return False, "No joinable quiz lobby is active."

        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return False, "Guild unavailable."
        member = guild.get_member(user_id)
        if member is None or member.bot:
            return False, "Only real server members can join."

        async with session.lock:
            if user_id in session.participants:
                return False, "You already joined this quiz lobby."
            session.participants.add(user_id)
            session.players[user_id] = QuizPlayerState(user_id=user_id)

        await self._refresh_lobby_message(session)
        return True, "You joined the quiz lobby."

    async def leave_lobby(self, guild_id: int, user_id: int) -> tuple[bool, str]:
        session = self._active_by_guild.get(guild_id)
        if not session or session.status != "lobby":
            return False, "No lobby is active right now."

        async with session.lock:
            if user_id not in session.participants:
                return False, "You are not in the current lobby."
            session.participants.remove(user_id)
            session.players.pop(user_id, None)

            if not session.participants:
                await self._cancel_session(session, "Lobby closed because everyone left.")
                return True, "You left the lobby."

            if session.host_user_id == user_id:
                session.host_user_id = sorted(session.participants)[0]

        await self._refresh_lobby_message(session)
        return True, "You left the quiz lobby."

    async def cancel_quiz(self, guild_id: int, actor: discord.Member) -> tuple[bool, str]:
        session = self._active_by_guild.get(guild_id)
        if not session:
            return False, "No active quiz to cancel."

        if actor.id != session.host_user_id and not actor.guild_permissions.manage_guild:
            return False, "Only the host or a moderator can cancel this quiz."

        await self._cancel_session(session, f"Quiz cancelled by {actor.display_name}.")
        return True, "Quiz cancelled."

    async def start_now(self, guild_id: int, actor: discord.Member) -> tuple[bool, str]:
        session = self._active_by_guild.get(guild_id)
        if not session or session.status != "lobby":
            return False, "No quiz lobby is currently waiting."

        if actor.id != session.host_user_id and not actor.guild_permissions.manage_guild:
            return False, "Only the host or a moderator can force-start the quiz."

        started = await self._begin_quiz(session, triggered_by=f"Manual start by {actor.display_name}")
        if not started:
            return False, "Quiz could not be started."
        return True, "Quiz started."

    async def submit_answer(
        self,
        interaction: discord.Interaction,
        session_id: str,
        question_index: int,
        choice_index: int,
    ) -> tuple[bool, str]:
        if not interaction.guild or not interaction.user:
            return False, "This interaction is no longer valid."

        member = interaction.guild.get_member(interaction.user.id)
        if member is None or member.bot:
            return False, "Only members can answer quiz questions."

        session = self._by_session_id.get(session_id)
        if not session or session.status != "running":
            return False, "This question is already closed."

        rate_key = (interaction.guild.id, interaction.user.id)
        now = utc_now()
        last_press = self._button_rate_limiter.get(rate_key)
        if last_press and (now - last_press).total_seconds() < 0.8:
            return False, "Slow down a bit."
        self._button_rate_limiter[rate_key] = now

        async with session.lock:
            if session.current_question_index != question_index:
                return False, "That round is already locked."
            if interaction.user.id not in session.participants:
                return False, "You are not a participant in this quiz."

            answers = session.answers_by_question.setdefault(question_index, {})
            if interaction.user.id in answers:
                return False, "You already locked an answer for this round."

            if question_index >= len(session.questions):
                return False, "Question not found."
            if session.question_started_at is None:
                return False, "Question timing was not initialized."

            question = session.questions[question_index]
            is_correct = choice_index == question.correct_index
            response_seconds = max(0.0, (now - session.question_started_at).total_seconds())
            answer = AnswerRecord(
                choice_index=choice_index,
                is_correct=is_correct,
                response_seconds=response_seconds,
                answered_at=now,
            )
            answers[interaction.user.id] = answer
            player = session.players.setdefault(
                interaction.user.id, QuizPlayerState(user_id=interaction.user.id)
            )
            player.answers[question_index] = answer

        letters = ["A", "B", "C", "D"]
        chosen = letters[choice_index] if 0 <= choice_index < len(letters) else str(choice_index)
        return True, f"Locked in **{chosen}**."

    async def run_daily_scheduler_tick(self) -> None:
        if not self.bot.user:
            return

        now_local = now_in_timezone(self.config.timezone)
        minute_key = now_local.strftime("%H:%M")
        today_str = now_local.date().isoformat()

        for guild in self.bot.guilds:
            cfg = await self.xp_service.get_guild_config(guild.id)
            if cfg.daily_quiz_time != minute_key:
                continue
            if cfg.last_daily_quiz_run_date == today_str:
                continue
            if guild.id in self._active_by_guild:
                continue
            if not cfg.quiz_channel_id:
                continue

            channel = guild.get_channel(cfg.quiz_channel_id)
            if not isinstance(channel, discord.TextChannel):
                continue

            category = self._daily_category_for(guild.id, now_local.date())
            started, _ = await self.start_lobby(
                guild=guild,
                channel=channel,
                host_user_id=self.bot.user.id,
                quiz_type="daily",
                category=category,
                difficulty="medium",
                question_count=cfg.questions_per_quiz,
            )
            if started:
                await self.xp_service.update_guild_config_field(
                    guild.id, "last_daily_quiz_run_date", today_str
                )

    async def get_daily_info(self, guild_id: int) -> dict[str, object]:
        cfg = await self.xp_service.get_guild_config(guild_id)
        active = self.get_active_daily_lobby(guild_id)
        seconds_remaining = seconds_until_next_time(cfg.daily_quiz_time, self.config.timezone)
        return {
            "scheduled_time": cfg.daily_quiz_time,
            "seconds_until_next": seconds_remaining,
            "active_lobby": active,
        }

    async def join_active_daily_lobby(self, guild_id: int, user_id: int) -> tuple[bool, str]:
        session = self.get_active_daily_lobby(guild_id)
        if not session:
            return False, "Daily quiz lobby is not active right now."
        return await self.join_lobby(guild_id, user_id)

    async def shutdown(self) -> None:
        sessions = list(self._active_by_guild.values())
        for session in sessions:
            await self._cancel_session(session, "Bot is shutting down.")

    async def _start_now_from_button(
        self, interaction: discord.Interaction, guild_id: int
    ) -> tuple[bool, str]:
        if not interaction.guild or not interaction.user:
            return False, "Interaction is invalid."
        member = interaction.guild.get_member(interaction.user.id)
        if member is None:
            return False, "Member not found."
        return await self.start_now(guild_id, member)

    async def _cancel_from_button(
        self, interaction: discord.Interaction, guild_id: int
    ) -> tuple[bool, str]:
        if not interaction.guild or not interaction.user:
            return False, "Interaction is invalid."
        member = interaction.guild.get_member(interaction.user.id)
        if member is None:
            return False, "Member not found."
        return await self.cancel_quiz(guild_id, member)

    async def _auto_start_after_delay(self, guild_id: int, delay_seconds: int) -> None:
        await asyncio.sleep(delay_seconds)
        session = self._active_by_guild.get(guild_id)
        if not session or session.status != "lobby":
            return
        await self._begin_quiz(session, triggered_by="Lobby timer expired")

    async def _begin_quiz(self, session: RuntimeQuizSession, triggered_by: str) -> bool:
        guild = self.bot.get_guild(session.guild_id)
        if guild is None:
            await self._cancel_session(session, "Guild unavailable.")
            return False

        channel = guild.get_channel(session.channel_id)
        if not isinstance(channel, discord.TextChannel):
            await self._cancel_session(session, "Quiz channel is unavailable.")
            return False

        cfg = await self.xp_service.get_guild_config(session.guild_id)
        async with session.lock:
            if session.status != "lobby":
                return False

            eligible_participants = self._human_participants(guild, session.participants)
            if len(eligible_participants) < cfg.min_quiz_players:
                await self._cancel_session(
                    session,
                    f"Not enough players joined. Need at least {cfg.min_quiz_players}.",
                )
                return False

            session.participants = set(eligible_participants)
            for user_id in eligible_participants:
                session.players.setdefault(user_id, QuizPlayerState(user_id=user_id))
            session.status = "running"

        await self.xp_service.db.execute(
            "UPDATE quiz_sessions SET status = 'running' WHERE session_id = ?",
            (session.session_id,),
        )

        if session.lobby_task and not session.lobby_task.done():
            session.lobby_task.cancel()

        if session.lobby_view:
            for child in session.lobby_view.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
            if session.lobby_message:
                try:
                    await session.lobby_message.edit(
                        embed=self._build_lobby_embed(guild, session, cfg, started=True),
                        view=session.lobby_view,
                    )
                except discord.HTTPException:
                    LOGGER.debug("Failed to edit lobby message during quiz start")

        try:
            recent_keys = set(self._recent_questions_by_guild[session.guild_id])
            fetched_questions = await self.trivia_api.fetch_questions(
                category=session.category,
                limit=session.question_count,
                difficulty=session.difficulty,
                exclude_questions=recent_keys,
            )

            # If the pool is small after excluding recent questions, backfill while keeping
            # no duplicates inside the same session.
            if len(fetched_questions) < session.question_count and recent_keys:
                relaxed = await self.trivia_api.fetch_questions(
                    category=session.category,
                    limit=session.question_count,
                    difficulty=session.difficulty,
                    exclude_questions=set(),
                )
                merged: list[TriviaQuestion] = []
                seen: set[str] = set()
                for question in [*fetched_questions, *relaxed]:
                    key = self._question_key(question.question)
                    if key in seen:
                        continue
                    seen.add(key)
                    merged.append(question)
                    if len(merged) >= session.question_count:
                        break
                fetched_questions = merged
            session.questions = fetched_questions
        except Exception:  # noqa: BLE001
            LOGGER.exception("Question fetch crashed.")
            await self._cancel_session(session, "Trivia source failed unexpectedly.")
            return False

        if len(session.questions) < session.question_count:
            available = len(session.questions)
            if available >= 2:
                requested = session.question_count
                session.question_count = available
                limited_embed = discord.Embed(
                    title="Limited Question Pool",
                    description=(
                        f"Requested **{requested}** questions for **{session.category}**, "
                        f"but only **{available}** matched. Starting with available questions."
                    ),
                    color=Theme.warning,
                )
                await channel.send(embed=limited_embed)
            else:
                await self._cancel_session(session, "Could not gather enough questions.")
                return False

        self._remember_recent_questions(session.guild_id, session.questions)

        intro = discord.Embed(
            title="Quiz Starting",
            description=(
                f"Category: **{session.category}**\n"
                f"Difficulty: **{session.difficulty}**\n"
                f"Questions: **{session.question_count}**\n"
                f"Players: **{len(session.participants)}**\n"
                f"Trigger: {triggered_by}"
            ),
            color=Theme.quiz,
        )
        await channel.send(embed=intro)

        for idx, question in enumerate(session.questions):
            if session.status != "running":
                break
            await self._run_question_round(
                guild=guild,
                channel=channel,
                session=session,
                question_index=idx,
                question=question,
                time_limit=cfg.question_time_limit_seconds,
            )

        if session.status == "running":
            await self._finish_session(session)
        return True

    async def _run_question_round(
        self,
        *,
        guild: discord.Guild,
        channel: discord.TextChannel,
        session: RuntimeQuizSession,
        question_index: int,
        question: TriviaQuestion,
        time_limit: int,
    ) -> None:
        effective_time_limit = self._resolve_round_time_limit(
            session.difficulty, time_limit
        )

        async with session.lock:
            session.current_question_index = question_index
            session.question_started_at = utc_now()
            session.answers_by_question[question_index] = {}

        letters = ["A", "B", "C", "D"]
        option_lines = [
            f"**{letters[idx]}** - {short_display(option, 96)}"
            for idx, option in enumerate(question.options[:4])
        ]
        embed = discord.Embed(
            title=f"Question {question_index + 1}/{session.question_count}",
            description=question.question,
            color=Theme.quiz,
        )
        embed.add_field(name="Category", value=question.category, inline=True)
        embed.add_field(name="Difficulty", value=session.difficulty, inline=True)
        embed.add_field(name="Timer", value=f"{effective_time_limit}s", inline=True)
        embed.add_field(name="Options", value="\n".join(option_lines), inline=False)
        embed.set_footer(text="One answer only. Fast correct answers score higher.")

        session_id = session.session_id
        all_answered_event = asyncio.Event()

        async def submit_handler(
            interaction: discord.Interaction, q_idx: int, choice_idx: int
        ) -> tuple[bool, str]:
            accepted, message = await self.submit_answer(
                interaction, session_id, q_idx, choice_idx
            )
            if accepted and await self._all_participants_answered(session, q_idx):
                all_answered_event.set()
            return accepted, message

        answer_view = QuizAnswerView(
            question_index=question_index,
            options=question.options,
            timeout=float(effective_time_limit),
            on_submit=submit_handler,
        )
        session.answer_view = answer_view
        message = await channel.send(embed=embed, view=answer_view)
        answer_view.message = message

        try:
            await asyncio.wait_for(
                all_answered_event.wait(), timeout=float(effective_time_limit)
            )
        except asyncio.TimeoutError:
            pass
        for child in answer_view.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        try:
            await message.edit(view=answer_view)
        except discord.HTTPException:
            pass

        outcome = await self._score_round(
            session, question_index, question, effective_time_limit
        )
        await self._persist_round_answers(session, question_index, question.category)
        await channel.send(
            embed=self._build_reveal_embed(guild, session, question, question_index, outcome)
        )
        await channel.send(embed=self._build_round_scoreboard_embed(guild, session, question_index))

    async def _score_round(
        self,
        session: RuntimeQuizSession,
        question_index: int,
        question: TriviaQuestion,
        time_limit: int,
    ) -> dict[str, object]:
        letters = ["A", "B", "C", "D"]
        correct_letter = letters[question.correct_index]
        correct_users: list[int] = []
        points_map: dict[int, int] = {}
        fastest_user_id: int | None = None
        fastest_time: float | None = None

        async with session.lock:
            answers = session.answers_by_question.get(question_index, {})
            for user_id, answer in answers.items():
                if not answer.is_correct:
                    continue
                response = min(float(time_limit), max(0.0, answer.response_seconds))
                speed_ratio = max(0.0, 1.0 - (response / max(1, time_limit)))
                speed_points = int(speed_ratio * QUIZ_POINTS_SPEED_CAP)
                total_points = QUIZ_POINTS_CORRECT + speed_points

                player = session.players.setdefault(user_id, QuizPlayerState(user_id=user_id))
                player.correct_count += 1
                if speed_points >= 20:
                    player.fast_bonus_count += 1
                player.score += total_points

                correct_users.append(user_id)
                points_map[user_id] = total_points
                if fastest_time is None or response < fastest_time:
                    fastest_time = response
                    fastest_user_id = user_id

        return {
            "correct_letter": correct_letter,
            "correct_users": correct_users,
            "points_map": points_map,
            "fastest_user_id": fastest_user_id,
            "fastest_time": fastest_time,
        }

    async def _persist_round_answers(
        self, session: RuntimeQuizSession, question_index: int, category: str
    ) -> None:
        answers = session.answers_by_question.get(question_index, {})
        if not answers:
            return

        rows = [
            (
                session.session_id,
                question_index,
                user_id,
                category,
                int(record.response_seconds * 1000),
                int(record.is_correct),
                record.answered_at.isoformat(),
            )
            for user_id, record in answers.items()
        ]
        await self.xp_service.db.executemany(
            """
            INSERT OR REPLACE INTO quiz_answers (
                session_id, question_index, user_id, category, response_ms, is_correct, answered_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    def _build_reveal_embed(
        self,
        guild: discord.Guild,
        session: RuntimeQuizSession,
        question: TriviaQuestion,
        question_index: int,
        outcome: dict[str, object],
    ) -> discord.Embed:
        embed = discord.Embed(
            title=f"Round {question_index + 1} Reveal",
            description=f"Correct answer: **{outcome['correct_letter']} - {question.correct_answer}**",
            color=Theme.success,
        )

        correct_users = [guild.get_member(uid) for uid in outcome["correct_users"]]  # type: ignore[index]
        correct_names = [member.display_name for member in correct_users if member]
        embed.add_field(
            name="Correct Players",
            value=", ".join(correct_names[:10]) if correct_names else "No one this round.",
            inline=False,
        )

        fastest_user_id = outcome["fastest_user_id"]  # type: ignore[index]
        fastest_time = outcome["fastest_time"]  # type: ignore[index]
        if fastest_user_id:
            fastest_member = guild.get_member(int(fastest_user_id))
            if fastest_member and fastest_time is not None:
                embed.add_field(
                    name="Fastest Correct",
                    value=f"{fastest_member.display_name} ({float(fastest_time):.2f}s)",
                    inline=True,
                )

        points_map: dict[int, int] = outcome["points_map"]  # type: ignore[assignment]
        if points_map:
            ordered = sorted(points_map.items(), key=lambda item: item[1], reverse=True)[:5]
            point_lines = []
            for uid, points in ordered:
                member = guild.get_member(uid)
                display = member.display_name if member else f"User {uid}"
                point_lines.append(f"{display}: +{points}")
            embed.add_field(name="Round Gains", value="\n".join(point_lines), inline=False)
        return embed

    def _build_round_scoreboard_embed(
        self, guild: discord.Guild, session: RuntimeQuizSession, question_index: int
    ) -> discord.Embed:
        sorted_players = self._sorted_player_states(session)
        lines: list[str] = []
        for rank, player in enumerate(sorted_players[:10], start=1):
            member = guild.get_member(player.user_id)
            name = member.display_name if member else f"User {player.user_id}"
            lines.append(f"**{rank}.** {name} - {player.score} pts")

        embed = discord.Embed(
            title=f"Scoreboard After Round {question_index + 1}",
            description="\n".join(lines) if lines else "No scores yet.",
            color=Theme.primary,
        )
        return embed

    async def _finish_session(self, session: RuntimeQuizSession) -> None:
        guild = self.bot.get_guild(session.guild_id)
        if guild is None:
            await self._cancel_session(session, "Guild unavailable at finish.")
            return
        channel = guild.get_channel(session.channel_id)
        if not isinstance(channel, discord.TextChannel):
            await self._cancel_session(session, "Channel unavailable at finish.")
            return

        cfg = await self.xp_service.get_guild_config(session.guild_id)
        sorted_players = self._sorted_player_states(session)
        participant_count = len(sorted_players)

        rows = [
            (
                session.session_id,
                player.user_id,
                player.score,
                player.correct_count,
                player.fast_bonus_count,
                session.created_at.isoformat(),
            )
            for player in sorted_players
        ]
        if rows:
            await self.xp_service.db.executemany(
                """
                INSERT OR REPLACE INTO quiz_participants (
                    session_id, user_id, score, correct_count, fast_bonus_count, joined_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

        final_embed = discord.Embed(title="Quiz Results", color=Theme.primary)
        if sorted_players:
            podium_lines = []
            labels = ["#1", "#2", "#3"]
            for idx, player in enumerate(sorted_players[:3]):
                member = guild.get_member(player.user_id)
                display = member.display_name if member else f"User {player.user_id}"
                label = labels[idx] if idx < len(labels) else "#"
                podium_lines.append(f"{label} {display} - {player.score} pts")
            final_embed.description = "\n".join(podium_lines)
        else:
            final_embed.description = "No valid participants."

        rewards_skipped = participant_count < cfg.min_quiz_players
        xp_lines: list[str] = []
        if not rewards_skipped:
            for rank, player in enumerate(sorted_players, start=1):
                member = guild.get_member(player.user_id)
                if member is None or member.bot:
                    continue

                base_xp = (
                    self.config.scoring.participation_xp
                    + player.correct_count * self.config.scoring.correct_answer_xp
                    + player.fast_bonus_count * self.config.scoring.fast_answer_bonus_xp
                )
                podium_bonus = 0
                if rank == 1:
                    podium_bonus = self.config.scoring.winner_bonus_xp
                elif rank == 2:
                    podium_bonus = max(5, self.config.scoring.winner_bonus_xp // 2)
                elif rank == 3:
                    podium_bonus = max(3, self.config.scoring.winner_bonus_xp // 3)

                user_before = await self.xp_service.get_user_stats(session.guild_id, player.user_id)
                await self.xp_service.add_quiz_participation_stats(
                    guild_id=session.guild_id,
                    user_id=player.user_id,
                    correct_count=player.correct_count,
                    won=rank == 1,
                    quiz_type=session.quiz_type,
                )
                user_after = await self.xp_service.get_user_stats(session.guild_id, player.user_id)

                streak_bonus = 0
                if (
                    session.quiz_type == "daily"
                    and user_before.last_daily_quiz_date != user_after.last_daily_quiz_date
                ):
                    streak_bonus = self.config.scoring.daily_streak_bonus_xp

                total_award = base_xp + podium_bonus + streak_bonus
                await self.xp_service.add_xp(
                    guild_id=session.guild_id,
                    user_id=player.user_id,
                    amount=total_award,
                    xp_type="quiz_xp",
                    guild=guild,
                    member=member,
                    allow_levelup_announce=True,
                )
                xp_lines.append(
                    f"{member.display_name}: +{total_award} XP "
                    f"(correct {player.correct_count}, fast {player.fast_bonus_count})"
                )
        else:
            final_embed.add_field(
                name="Rewards",
                value=f"Skipped XP rewards: minimum {cfg.min_quiz_players} players required.",
                inline=False,
            )

        if xp_lines:
            final_embed.add_field(name="XP Rewards", value="\n".join(xp_lines[:10]), inline=False)

        await channel.send(embed=final_embed)
        await self.xp_service.db.execute(
            """
            UPDATE quiz_sessions
            SET status = 'completed', ended_at = ?
            WHERE session_id = ?
            """,
            (utc_now().isoformat(), session.session_id),
        )
        await self._cleanup_session(session)

    async def _cancel_session(self, session: RuntimeQuizSession, reason: str) -> None:
        guild = self.bot.get_guild(session.guild_id)
        channel = guild.get_channel(session.channel_id) if guild else None

        await self.xp_service.db.execute(
            """
            UPDATE quiz_sessions
            SET status = 'cancelled', ended_at = ?
            WHERE session_id = ?
            """,
            (utc_now().isoformat(), session.session_id),
        )

        if session.lobby_task and not session.lobby_task.done():
            session.lobby_task.cancel()

        if session.lobby_view:
            for child in session.lobby_view.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
            if session.lobby_message:
                try:
                    await session.lobby_message.edit(view=session.lobby_view)
                except discord.HTTPException:
                    pass

        if isinstance(channel, discord.TextChannel):
            embed = discord.Embed(title="Quiz Cancelled", description=reason, color=Theme.warning)
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass

        await self._cleanup_session(session)

    async def _cleanup_session(self, session: RuntimeQuizSession) -> None:
        self._active_by_guild.pop(session.guild_id, None)
        self._by_session_id.pop(session.session_id, None)

    async def _refresh_lobby_message(self, session: RuntimeQuizSession) -> None:
        if session.lobby_message is None:
            return
        guild = self.bot.get_guild(session.guild_id)
        if guild is None:
            return
        cfg = await self.xp_service.get_guild_config(session.guild_id)
        try:
            await session.lobby_message.edit(
                embed=self._build_lobby_embed(guild, session, cfg),
                view=session.lobby_view,
            )
        except discord.HTTPException:
            LOGGER.debug("Failed to refresh lobby message for session %s", session.session_id)

    def _build_lobby_embed(
        self,
        guild: discord.Guild,
        session: RuntimeQuizSession,
        cfg: object,
        *,
        started: bool = False,
    ) -> discord.Embed:
        title = "Daily Quiz Lobby" if session.quiz_type == "daily" else "Trivia Lobby"
        embed = discord.Embed(title=title, color=Theme.quiz)
        embed.add_field(name="Category", value=session.category, inline=True)
        embed.add_field(name="Difficulty", value=session.difficulty, inline=True)
        embed.add_field(name="Questions", value=str(session.question_count), inline=True)
        embed.add_field(name="Minimum Players", value=str(getattr(cfg, "min_quiz_players", 2)), inline=True)

        players = []
        for user_id in sorted(session.participants):
            member = guild.get_member(user_id)
            players.append(member.display_name if member else f"User {user_id}")
        embed.add_field(
            name=f"Players Joined ({len(players)})",
            value="\n".join(players[:20]) if players else "No players joined yet.",
            inline=False,
        )

        host = guild.get_member(session.host_user_id)
        embed.set_footer(
            text=(
                f"Host: {host.display_name if host else session.host_user_id}"
                + (" | Quiz started" if started else " | Join before timer ends")
            )
        )
        return embed

    async def _ondemand_cooldown_remaining(self, guild_id: int, minutes: int) -> int:
        row = await self.xp_service.db.fetchone(
            """
            SELECT ended_at
            FROM quiz_sessions
            WHERE guild_id = ?
              AND quiz_type = 'ondemand'
              AND ended_at IS NOT NULL
            ORDER BY ended_at DESC
            LIMIT 1
            """,
            (guild_id,),
        )
        if row is None or row["ended_at"] is None:
            return 0

        try:
            ended_at = datetime.fromisoformat(str(row["ended_at"]))
        except ValueError:
            return 0

        remaining = int((ended_at + timedelta(minutes=minutes) - utc_now()).total_seconds())
        return max(0, remaining)

    def _sorted_player_states(self, session: RuntimeQuizSession) -> list[QuizPlayerState]:
        players = [session.players[user_id] for user_id in session.participants if user_id in session.players]
        return sorted(
            players,
            key=lambda p: (p.score, p.correct_count, p.fast_bonus_count, -p.user_id),
            reverse=True,
        )

    def _human_participants(self, guild: discord.Guild, users: set[int]) -> list[int]:
        participants: list[int] = []
        for user_id in users:
            member = guild.get_member(user_id)
            if member and not member.bot:
                participants.append(user_id)
        return participants

    def _resolve_category(self, requested: str | None, default: str) -> str:
        if requested and requested.lower() == "random":
            return self.trivia_api.choose_random_category()
        clean = (requested or default or "general").strip().lower()
        if clean not in SUPPORTED_CATEGORIES:
            return "general"
        return clean

    def _resolve_difficulty(self, requested: str | None) -> str:
        return self.trivia_api.normalize_difficulty(requested)

    def _resolve_round_time_limit(self, difficulty: str, configured_limit: int) -> int:
        base_limit = max(5, int(configured_limit))
        if difficulty == "hard":
            return 35
        return base_limit

    async def _all_participants_answered(
        self, session: RuntimeQuizSession, question_index: int
    ) -> bool:
        async with session.lock:
            answered_count = len(session.answers_by_question.get(question_index, {}))
            participant_count = len(session.participants)
        return participant_count > 0 and answered_count >= participant_count

    def _daily_category_for(self, guild_id: int, current_date: date) -> str:
        index = (current_date.toordinal() + guild_id) % len(SUPPORTED_CATEGORIES)
        return SUPPORTED_CATEGORIES[index]

    def _remember_recent_questions(
        self, guild_id: int, questions: list[TriviaQuestion]
    ) -> None:
        history = self._recent_questions_by_guild[guild_id]
        for question in questions:
            history.append(self._question_key(question.question))

    @staticmethod
    def _question_key(text: str) -> str:
        return " ".join(text.strip().lower().split())

