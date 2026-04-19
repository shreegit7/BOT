from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass

import discord
from PIL import Image, ImageDraw, ImageFont

from bot.utils.formatting import compact_number, progress_bar, short_display
from bot.utils.time import format_minutes


@dataclass(slots=True)
class RankCardPayload:
    username: str
    avatar_bytes: bytes | None
    level: int
    total_xp: int
    rank_position: int
    progress_ratio: float
    level_xp_gained: int
    level_xp_needed: int
    chat_xp: int
    voice_xp: int
    quiz_xp: int
    voice_minutes: int
    title_label: str


def _load_font(size: int) -> ImageFont.ImageFont:
    for candidate in ("seguiemj.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _mask_circle(size: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size, size), fill=255)
    return mask


def _render_sync(payload: RankCardPayload) -> io.BytesIO:
    width, height = 960, 320
    image = Image.new("RGB", (width, height), "#111827")
    draw = ImageDraw.Draw(image)

    for y in range(height):
        mix = y / max(1, height - 1)
        r = int(23 + mix * 18)
        g = int(32 + mix * 24)
        b = int(48 + mix * 40)
        draw.line((0, y, width, y), fill=(r, g, b))

    draw.rounded_rectangle((24, 24, width - 24, height - 24), radius=22, fill="#1F2937")
    draw.rounded_rectangle((38, 38, width - 38, height - 38), radius=18, outline="#334155", width=2)

    avatar_size = 132
    avatar_x, avatar_y = 58, 94
    if payload.avatar_bytes:
        avatar = Image.open(io.BytesIO(payload.avatar_bytes)).convert("RGB").resize(
            (avatar_size, avatar_size)
        )
        mask = _mask_circle(avatar_size)
        image.paste(avatar, (avatar_x, avatar_y), mask)
    else:
        draw.ellipse(
            (avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size),
            fill="#0F172A",
            outline="#475569",
            width=2,
        )

    title_font = _load_font(34)
    body_font = _load_font(20)
    small_font = _load_font(16)
    badge_font = _load_font(24)

    username = short_display(payload.username, 28)
    draw.text((220, 56), username, font=title_font, fill="#E2E8F0")

    if payload.title_label:
        draw.rounded_rectangle((220, 98, 480, 130), radius=10, fill="#0B3A5B")
        draw.text((232, 104), short_display(payload.title_label, 24), font=small_font, fill="#93C5FD")

    badge_text = f"LVL {payload.level}"
    badge_w = draw.textlength(badge_text, font=badge_font) + 24
    draw.rounded_rectangle((width - 70 - badge_w, 56, width - 70, 92), radius=10, fill="#F59E0B")
    draw.text((width - 58 - badge_w, 61), badge_text, font=badge_font, fill="#111827")

    draw.text((220, 144), f"Rank #{payload.rank_position}", font=body_font, fill="#38BDF8")
    draw.text((390, 144), f"Total XP {compact_number(payload.total_xp)}", font=body_font, fill="#E2E8F0")

    bar_x1, bar_x2 = 220, width - 70
    bar_y1, bar_y2 = 182, 212
    draw.rounded_rectangle((bar_x1, bar_y1, bar_x2, bar_y2), radius=12, fill="#0F172A")
    fill_width = int((bar_x2 - bar_x1) * max(0.0, min(1.0, payload.progress_ratio)))
    draw.rounded_rectangle((bar_x1, bar_y1, bar_x1 + fill_width, bar_y2), radius=12, fill="#22D3EE")

    progress_text = (
        f"{compact_number(payload.level_xp_gained)}/{compact_number(payload.level_xp_needed)} XP"
    )
    draw.text((220, 220), progress_text, font=small_font, fill="#CBD5E1")
    draw.text((470, 220), progress_bar(payload.progress_ratio, 20), font=small_font, fill="#67E8F9")

    draw.text((58, 248), f"Chat XP  {compact_number(payload.chat_xp)}", font=small_font, fill="#FBBF24")
    draw.text((258, 248), f"Voice XP  {compact_number(payload.voice_xp)}", font=small_font, fill="#86EFAC")
    draw.text((478, 248), f"Quiz XP  {compact_number(payload.quiz_xp)}", font=small_font, fill="#A5B4FC")
    draw.text(
        (668, 248),
        f"Voice Time  {format_minutes(payload.voice_minutes)}",
        font=small_font,
        fill="#E2E8F0",
    )

    output = io.BytesIO()
    image.save(output, "PNG")
    output.seek(0)
    return output


async def render_rank_card(
    *,
    member: discord.abc.User,
    level: int,
    total_xp: int,
    rank_position: int,
    progress_ratio: float,
    level_xp_gained: int,
    level_xp_needed: int,
    chat_xp: int,
    voice_xp: int,
    quiz_xp: int,
    voice_minutes: int,
    title_label: str,
) -> io.BytesIO:
    avatar_bytes: bytes | None
    try:
        avatar_bytes = await member.display_avatar.replace(size=256).read()
    except (discord.HTTPException, discord.NotFound):
        avatar_bytes = None

    payload = RankCardPayload(
        username=str(member.display_name),
        avatar_bytes=avatar_bytes,
        level=level,
        total_xp=total_xp,
        rank_position=rank_position,
        progress_ratio=progress_ratio,
        level_xp_gained=level_xp_gained,
        level_xp_needed=level_xp_needed,
        chat_xp=chat_xp,
        voice_xp=voice_xp,
        quiz_xp=quiz_xp,
        voice_minutes=voice_minutes,
        title_label=title_label,
    )
    return await asyncio.to_thread(_render_sync, payload)
