from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont


@dataclass(slots=True)
class LeaderboardCardRow:
    rank: int
    name: str
    primary: str
    secondary: str = ""


def _load_font(size: int) -> ImageFont.ImageFont:
    for candidate in ("seguiemj.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _short(text: str, limit: int) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return clean[: max(1, limit - 1)] + "..."


def _render_sync(*, title: str, subtitle: str, rows: list[LeaderboardCardRow]) -> io.BytesIO:
    width, height = 1100, 760
    image = Image.new("RGB", (width, height), "#0B1020")
    draw = ImageDraw.Draw(image)

    for y in range(height):
        ratio = y / max(1, height - 1)
        r = int(10 + ratio * 14)
        g = int(16 + ratio * 22)
        b = int(30 + ratio * 34)
        draw.line((0, y, width, y), fill=(r, g, b))

    draw.rounded_rectangle((28, 28, width - 28, height - 28), radius=24, fill="#111827")
    draw.rounded_rectangle((46, 46, width - 46, height - 46), radius=18, outline="#334155", width=2)

    title_font = _load_font(44)
    subtitle_font = _load_font(21)
    row_font = _load_font(24)
    row_small_font = _load_font(18)

    draw.text((74, 72), _short(title, 40), font=title_font, fill="#E2E8F0")
    draw.text((74, 128), _short(subtitle, 80), font=subtitle_font, fill="#93C5FD")

    row_top = 178
    row_height = 52
    for idx, row in enumerate(rows[:10]):
        y = row_top + (idx * row_height)
        if idx % 2 == 0:
            draw.rounded_rectangle((70, y - 2, width - 70, y + row_height - 8), radius=10, fill="#0F172A")

        left_text = f"{row.rank}. {_short(row.name, 26)}"
        draw.text((86, y + 8), left_text, font=row_font, fill="#E5E7EB")
        draw.text((470, y + 8), _short(row.primary, 52), font=row_font, fill="#67E8F9")
        if row.secondary:
            draw.text((760, y + 11), _short(row.secondary, 40), font=row_small_font, fill="#A5B4FC")

    output = io.BytesIO()
    image.save(output, "PNG")
    output.seek(0)
    return output


async def render_leaderboard_card(
    *,
    title: str,
    subtitle: str,
    rows: list[LeaderboardCardRow],
) -> io.BytesIO:
    return await asyncio.to_thread(_render_sync, title=title, subtitle=subtitle, rows=rows)

