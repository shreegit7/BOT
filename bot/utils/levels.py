from __future__ import annotations


def xp_needed_for_next_level(level: int) -> int:
    level = max(1, level)
    return 100 + (level - 1) * 75


def total_xp_for_level(level: int) -> int:
    if level <= 1:
        return 0

    total = 0
    current = 1
    while current < level:
        total += xp_needed_for_next_level(current)
        current += 1
    return total


def level_from_total_xp(total_xp: int) -> int:
    xp = max(0, total_xp)
    level = 1
    spent = 0

    while True:
        needed = xp_needed_for_next_level(level)
        if spent + needed > xp:
            return level
        spent += needed
        level += 1


def progress_in_level(total_xp: int) -> tuple[int, int, int, float]:
    level = level_from_total_xp(total_xp)
    level_start = total_xp_for_level(level)
    level_end = total_xp_for_level(level + 1)
    gained = max(0, total_xp - level_start)
    needed = max(1, level_end - level_start)
    return level, gained, needed, min(1.0, gained / needed)
