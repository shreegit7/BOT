from __future__ import annotations

import re

import discord


class Theme:
    primary = discord.Color(0x4A90E2)
    success = discord.Color(0x2ECC71)
    warning = discord.Color(0xF1C40F)
    danger = discord.Color(0xE74C3C)
    neutral = discord.Color(0x95A5A6)
    quiz = discord.Color(0x1ABC9C)
    levelup = discord.Color(0xF39C12)


def progress_bar(ratio: float, length: int = 16) -> str:
    ratio = max(0.0, min(1.0, ratio))
    filled = int(round(ratio * length))
    return "#" * filled + "-" * (length - filled)


def compact_number(value: int) -> str:
    return f"{int(value):,}"


def normalize_for_spam_check(text: str) -> str:
    lowered = text.lower().strip()
    lowered = re.sub(r"\s+", " ", lowered)
    return re.sub(r"[^a-z0-9 ]", "", lowered)


def short_display(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3].rstrip() + "..."
