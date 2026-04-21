# Friend Server XP + Trivia Bot

Production-ready Discord bot for private friend servers:
- Unified XP system (chat + voice + quiz)
- Leveling, role milestones, and titles
- Rank cards (Pillow) + leaderboards
- Daily scheduled quiz + on-demand multiplayer quiz
- Button-based quiz gameplay and compact embeds
- SQLite persistence with automatic schema creation

## Stack
- Python 3.11+
- `discord.py` 2.x (slash commands + views)
- `aiohttp` (trivia API + optional health route)
- `sqlite3` (local database)
- `Pillow` (rank card image rendering)
- `python-dotenv` (env config)

## Project Structure
```text
main.py
bot/
  __init__.py
  config.py
  database.py
  logging_setup.py
  models.py
  utils/
    levels.py
    time.py
    formatting.py
    rank_card.py
  services/
    xp_service.py
    voice_service.py
    trivia_api.py
    quiz_service.py
  views/
    quiz_views.py
  cogs/
    general.py
    xp.py
    quiz.py
    admin.py
data/
  bot.db (auto-created)
logs/
  bot.log (auto-created)
.env.example
requirements.txt
README.md
```

## Setup
1. Create and activate a Python 3.11+ virtual environment.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill values.
4. Start the bot:
   ```bash
   python main.py
   ```

## Required Environment Variables
- `DISCORD_TOKEN`: your bot token
- `DEFAULT_PREFIX`: legacy prefix (slash commands are primary)
- `TZ`: timezone used for daily quiz scheduling

## Optional Environment Variables
- `QUIZAPI_KEY`: optional secondary trivia provider key (QuizAPI)
- `DATABASE_PATH` (default: `data/bot.db`)
- `LOG_LEVEL` (default: `INFO`)
- `SYNC_COMMANDS_ON_STARTUP` (default: `true`)
- `HEALTHCHECK_ENABLED` (default: auto-on if `PORT` exists)
- `HEALTH_PORT` (default: `PORT` or `8080`)
- `PORT` (Render sets this automatically)

## Discord Bot Permissions / Intents
Enable these bot intents in the Developer Portal:
- Server Members Intent
- Message Content Intent

Recommended bot permissions:
- Send Messages
- Embed Links
- Attach Files
- Read Message History
- Add Reactions
- Use External Emojis (optional)
- Manage Roles (if using level-role rewards)
- View Channels
- Connect / Speak not required for this bot

## Commands
### User
- `/rank [user]`
- `/profile [user]`
- `/leaderboard metric:[overall|voice|quiz|stats] timeframe:[all-time|weekly]` (includes graphical leaderboard card)
- `/dailyquiz [join:true|false]`

### Quiz
- `/quiz start [category] [difficulty] [questions]`
- `/quiz join`
- `/quiz leave`
- `/quiz category <category>` (manage guild required)
- `/quiz cancel`

### Admin Config
- `/config quiz_channel <channel>`
- `/config levelup_channel <channel>`
- `/config leaderboard_channel <channel>`
- `/config set_leaderboard_interval <minutes>` (`0` disables auto updates)
- `/config voice_xp <on_off>`
- `/config set_voice_interval <minutes>`
- `/config chat_xp <on_off>`
- `/config set_daily_quiz_time <HH:MM>`
- `/config set_level_role <level> <role> [title_label]`
- `/config set_quiz_cooldown <minutes>` (`0` disables cooldown)
- `/config quiz_cooldown <on_off>`
- `/config set_min_players <count>`

## Anti-Abuse + Fairness Rules
- Chat XP cooldown per user
- Minimum meaningful message length
- Command-like messages excluded from chat XP
- Repeated copy-paste style messages filtered
- Voice XP only in non-solo human calls
- AFK channel ignored for voice XP
- Self-deafened users do not receive voice XP by default
- One active quiz per guild
- Minimum players required for quiz rewards
- One answer per user per question
- On-demand quiz cooldown per guild
- Daily streak update guarded against duplicate same-day farming

## Trivia Source + Fallback
- Primary provider: Open Trivia DB (`https://opentdb.com/api.php`)
- Secondary provider: QuizAPI (`Authorization: Bearer ...`) when `QUIZAPI_KEY` is set
- Robust retries and timeout handling
- Local fallback question bank automatically used when providers fail or are unavailable
- Multiple-choice options are synthesized when source provides only Q/A

## Render Deployment
1. Push this project to your Git repository.
2. Create a new **Web Service** on Render.
3. Set Build Command:
   ```bash
   pip install -r requirements.txt
   ```
4. Set Start Command:
   ```bash
   python main.py
   ```
5. Add environment variables from `.env.example` (real values).
6. Ensure `DISCORD_TOKEN` is set.
7. (Optional) Keep `HEALTHCHECK_ENABLED=true` so `/health` is available.

## Startup Behavior
- Creates `data/bot.db` and all tables automatically on first run.
- Loads cogs and slash commands.
- Restores voice-session tracking state.
- Starts background loops:
  - voice XP award loop
  - daily quiz scheduler

## Manual Validation Checklist
- Bot starts cleanly with `python main.py`
- Database file and schema auto-create
- Chat XP applies with cooldown and message quality checks
- Voice XP awards only in active human group calls
- `/rank` works with image card (fallback embed if image fails)
- `/leaderboard` ordering is correct
- Daily quiz auto-lobby appears at configured time
- On-demand `/quiz start` supports category + difficulty + question count
- API questions load when key is valid
- Fallback questions load when API is down or key missing
- Admin config persists across restarts
