"""Pure scoring math. No database, no web code: numbers in, points out."""
import math

TRIM_MIN_JUDGES = 5  # only drop high/low scores when there are at least this many
MAX_POINTS = 5


def round_half_up(x: float) -> int:
    """Round .5 up. Python's round() uses banker's rounding: round(0.5) == 0."""
    return math.floor(x + 0.5)


def trimmed_total(scores: list[int]) -> int:
    """Sum a performer's stars, dropping one highest and one lowest if there are enough judges."""
    if len(scores) >= TRIM_MIN_JUDGES:
        ordered = sorted(scores)
        return sum(ordered[1:-1])
    return sum(scores)


def competition_ranks(totals: dict[int, int]) -> dict[int, int]:
    """Rank by total, highest first. Ties share a rank and the next rank skips: 1, 1, 3."""
    ordered = sorted(totals.values(), reverse=True)
    return {pid: ordered.index(total) + 1 for pid, total in totals.items()}


def rank_to_points(rank: int, performer_count: int) -> int:
    """Spread ranks evenly across 5 down to 1."""
    if performer_count <= 1:
        return MAX_POINTS
    return MAX_POINTS - round_half_up(4 * (rank - 1) / (performer_count - 1))


def task_points(scores_by_performer: dict[int, list[int]]) -> dict[int, int]:
    """Turn every judge's stars for one task into 1 to 5 Taskmaster points per performer."""
    if not scores_by_performer:
        return {}
    totals = {pid: trimmed_total(s) for pid, s in scores_by_performer.items()}
    ranks = competition_ranks(totals)
    count = len(totals)
    return {pid: rank_to_points(ranks[pid], count) for pid in totals}