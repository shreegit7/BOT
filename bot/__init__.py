from __future__ import annotations

import logging
import socket

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from bot.config import AppConfig
from bot.database import Database
from bot.services.quiz_service import QuizService
from bot.services.trivia_api import TriviaAPI
from bot.services.voice_service import VoiceService
from bot.services.xp_service import XPService

LOGGER = logging.getLogger(__name__)


def _iter_exception_chain(error: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    current: BaseException | None = error
    seen: set[int] = set()

    while current is not None and id(current) not in seen:
        chain.append(current)
        seen.add(id(current))

        if isinstance(current, app_commands.CommandInvokeError) and current.original:
            next_error = current.original
        elif current.__cause__ is not None:
            next_error = current.__cause__
        elif current.__context__ is not None and not current.__suppress_context__:
            next_error = current.__context__
        else:
            next_error = None

        current = next_error if isinstance(next_error, BaseException) else None

    return chain


def _is_network_error(error: BaseException) -> bool:
    network_types = (
        aiohttp.ClientError,
        discord.ConnectionClosed,
        discord.GatewayNotFound,
        socket.gaierror,
        ConnectionError,
        TimeoutError,
    )
    return any(isinstance(exc, network_types) for exc in _iter_exception_chain(error))


class FriendXpTriviaBot(commands.Bot):
    def __init__(self, *, config: AppConfig, database: Database) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.messages = True
        intents.message_content = True
        intents.voice_states = True

        super().__init__(
            command_prefix=config.default_prefix,
            intents=intents,
            help_command=None,
        )
        self.config = config
        self.db = database

        self.xp_service = XPService(database=database, config=config)
        self.trivia_api = TriviaAPI(quizapi_key=config.quizapi_key)
        self.voice_service = VoiceService(xp_service=self.xp_service)
        self.quiz_service = QuizService(
            bot=self,
            xp_service=self.xp_service,
            trivia_api=self.trivia_api,
            config=config,
        )
        self._guild_sync_done = False

    async def setup_hook(self) -> None:
        self.tree.on_error = self._on_app_command_error

        extensions = [
            "bot.cogs.general",
            "bot.cogs.xp",
            "bot.cogs.quiz",
            "bot.cogs.admin",
        ]
        for extension in extensions:
            await self.load_extension(extension)

        if self.config.sync_commands_on_startup:
            try:
                synced = await self.tree.sync()
                LOGGER.info("Synced %s application commands.", len(synced))
            except Exception:  # noqa: BLE001
                LOGGER.exception("Failed to sync application commands.")

    async def on_ready(self) -> None:
        if self.user:
            LOGGER.info("Logged in as %s (%s)", self.user, self.user.id)
        if self.config.sync_commands_on_startup and not self._guild_sync_done:
            synced_total = 0
            for guild in self.guilds:
                try:
                    synced = await self.tree.sync(guild=guild)
                    synced_total += len(synced)
                except Exception:  # noqa: BLE001
                    LOGGER.exception(
                        "Failed guild command sync for guild_id=%s", guild.id
                    )
            LOGGER.info(
                "Guild command sync completed for %s guild(s), %s command entries.",
                len(self.guilds),
                synced_total,
            )
            self._guild_sync_done = True

    async def _on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        network_error = _is_network_error(error)
        if network_error:
            LOGGER.warning("Application command failed due to network/DNS issue: %s", error)
            return

        LOGGER.exception("Application command error: %s", error)

        message = "Something went wrong while running that command."
        if isinstance(error, app_commands.MissingPermissions):
            message = "You do not have permission to use that command."
        elif isinstance(error, app_commands.CommandOnCooldown):
            message = f"Slow down. Try again in {error.retry_after:.1f}s."
        elif isinstance(error, app_commands.CheckFailure):
            message = "You are not allowed to use that command."

        if interaction.response.is_done():
            try:
                await interaction.followup.send(message, ephemeral=True)
            except (discord.HTTPException, aiohttp.ClientError, OSError, TimeoutError):
                pass
        else:
            try:
                await interaction.response.send_message(message, ephemeral=True)
            except (discord.HTTPException, aiohttp.ClientError, OSError, TimeoutError):
                pass

    async def close(self) -> None:
        try:
            await self.quiz_service.shutdown()
        except Exception:  # noqa: BLE001
            LOGGER.exception("Error shutting down quiz service.")
        try:
            await self.trivia_api.close()
        except Exception:  # noqa: BLE001
            LOGGER.exception("Error closing trivia API client.")
        try:
            await self.db.close()
        except Exception:  # noqa: BLE001
            LOGGER.exception("Error closing database.")
        await super().close()
