from __future__ import annotations

import asyncio
import logging

from aiohttp import web

from bot import FriendXpTriviaBot
from bot.config import AppConfig
from bot.database import Database
from bot.logging_setup import setup_logging

LOGGER = logging.getLogger(__name__)


async def _start_health_server(port: int) -> web.AppRunner:
    app = web.Application()

    async def healthcheck(_: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    app.router.add_get("/health", healthcheck)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    LOGGER.info("Health endpoint enabled on port %s", port)
    return runner


async def _run() -> None:
    config = AppConfig.load()
    setup_logging(config.log_level)

    database = Database(config.database_path)
    await database.connect()

    health_runner: web.AppRunner | None = None
    if config.enable_healthcheck:
        health_runner = await _start_health_server(config.health_port)

    bot = FriendXpTriviaBot(config=config, database=database)
    try:
        await bot.start(config.discord_token)
    finally:
        if health_runner is not None:
            await health_runner.cleanup()
        await bot.close()


if __name__ == "__main__":
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        LOGGER.info("Shutting down bot (keyboard interrupt)")
