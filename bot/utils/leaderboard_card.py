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
    width, height = 1180, 760
    image = Image.new("RGB", (width, height), "#1A1030")
    draw = ImageDraw.Draw(image)

    # Diagonal purple gradient background
    for y in range(height):
        y_ratio = y / max(1, height - 1)
        for x in range(width):
            x_ratio = x / max(1, width - 1)
            mix = (x_ratio * 0.55) + (y_ratio * 0.45)
            r = int(44 + mix * 40)
            g = int(24 + mix * 24)
            b = int(82 + mix * 70)
            image.putpixel((x, y), (r, g, b))

    # Add subtle diagonal accents
    for i in range(-height, width, 120):
        draw.polygon(
            [(i, 0), (i + 70, 0), (i + height + 70, height), (i + height, height)],
            fill=(255, 255, 255, 8),
        )

    # Outer and inner containers
    draw.rounded_rectangle((22, 22, width - 22, height - 22), radius=28, fill="#2B1C4F")
    draw.rounded_rectangle((38, 38, width - 38, height - 38), radius=20, outline="#7C5CD6", width=2)

    # Header band
    draw.rounded_rectangle((58, 54, width - 58, 142), radius=16, fill="#5F2EB3")
    draw.rounded_rectangle((58, 120, width - 58, 142), radius=10, fill="#6D35CC")

    title_font = _load_font(50)
    subtitle_font = _load_font(22)
    header_font = _load_font(16)
    row_font = _load_font(23)
    row_small_font = _load_font(17)

    # Trophy-styled title
    draw.text((84, 70), f"🏆 {_short(title.upper(), 28)} 🏆", font=title_font, fill="#F9E9FF")
    draw.text((84, 112), _short(subtitle, 80), font=subtitle_font, fill="#E6D4FF")

    # Table column header
    table_x1, table_x2 = 62, width - 62
    header_y1, header_y2 = 162, 198
    draw.rounded_rectangle((table_x1, header_y1, table_x2, header_y2), radius=8, fill="#45227F")
    draw.text((88, 171), "RANK", font=header_font, fill="#DCCBFF")
    draw.text((210, 171), "PLAYER", font=header_font, fill="#DCCBFF")
    draw.text((660, 171), "POINTS", font=header_font, fill="#DCCBFF")
    draw.text((900, 171), "DETAILS", font=header_font, fill="#DCCBFF")

    row_top = 210
    row_height = 50
    if not rows:
        empty_font = _load_font(28)
        help_font = _load_font(20)
        draw.text((84, row_top + 40), "No leaderboard data yet.", font=empty_font, fill="#F2E8FF")
        draw.text(
            (84, row_top + 84),
            "Users will appear here after earning XP or using /profile.",
            font=help_font,
            fill="#D5C1FF",
        )
    else:
        for idx, row in enumerate(rows[:10]):
            y = row_top + (idx * row_height)
            row_fill = "#6C35C7" if idx % 2 == 0 else "#5C2AAD"
            draw.rounded_rectangle((70, y, width - 70, y + row_height - 6), radius=8, fill=row_fill)

            rank_text = f"{row.rank:02}"
            draw.text((92, y + 10), rank_text, font=row_font, fill="#FFF3B0")
            draw.text((210, y + 10), _short(row.name, 33), font=row_font, fill="#FFFFFF")
            draw.text((660, y + 10), _short(row.primary, 24), font=row_font, fill="#FDFDFD")
            if row.secondary:
                draw.text((900, y + 14), _short(row.secondary, 24), font=row_small_font, fill="#EBD8FF")

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
