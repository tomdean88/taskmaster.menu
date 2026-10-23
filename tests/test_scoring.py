import pytest

from app.scoring import (
    competition_ranks,
    rank_to_points,
    round_half_up,
    task_points,
    trimmed_total,
)


def test_round_half_up_differs_from_builtin():
    assert round(0.5) == 0  # Python's banker's rounding, the trap we're avoiding
    assert round_half_up(0.5) == 1
    assert round_half_up(2.5) == 3
    assert round_half_up(1.4) == 1


def test_trim_drops_one_high_and_one_low():
    assert trimmed_total([1, 3, 3, 4, 5]) == 10


def test_trim_drops_only_one_of_each():
    assert trimmed_total([5, 5, 5, 1, 1]) == 11  # one 5 and one 1 dropped, not all of them


def test_no_trim_with_few_judges():
    assert trimmed_total([1, 5, 3]) == 9


def test_competition_ranks_with_ties():
    assert competition_ranks({1: 32, 2: 32, 3: 27}) == {1: 1, 2: 1, 3: 3}


def test_nine_performers_spread_across_bands():
    # The worked example from our planning chat: one score each, so no trimming.
    totals = [32, 30, 27, 25, 24, 21, 18, 15, 9]
    scores = {pid: [t] for pid, t in enumerate(totals, start=1)}
    points = task_points(scores)
    assert [points[pid] for pid in range(1, 10)] == [5, 4, 4, 3, 3, 2, 2, 1, 1]


def test_tied_performers_share_points():
    assert task_points({1: [10], 2: [10], 3: [5]}) == {1: 5, 2: 5, 3: 1}


def test_single_performer_gets_five():
    assert task_points({1: [3]}) == {1: 5}


def test_no_performers_gives_no_points():
    assert task_points({}) == {}


def test_trim_blunts_a_single_burying_vote():
    honest = {1: [4, 4, 4, 4, 4], 2: [3, 3, 3, 3, 3]}
    buried = {1: [4, 4, 4, 4, 1], 2: [3, 3, 3, 3, 3]}  # one judge tanks performer 1
    assert task_points(honest) == task_points(buried)

def test_everyone_tied_all_get_five():
    assert task_points({1: [3], 2: [3], 3: [3]}) == {1: 5, 2: 5, 3: 5}


def test_two_way_tie_at_the_bottom():
    assert task_points({1: [10], 2: [8], 3: [5], 4: [5]}) == {1: 5, 2: 4, 3: 2, 4: 2}


def test_two_performers_get_five_and_one():
    assert task_points({1: [10], 2: [5]}) == {1: 5, 2: 1}


def test_four_judges_are_not_trimmed():
    assert trimmed_total([1, 2, 3, 4]) == 10


def test_five_judges_are_trimmed():
    assert trimmed_total([1, 2, 3, 4, 5]) == 9


def test_single_performer_rank_gives_five():
    assert rank_to_points(1, 1) == 5


@pytest.mark.parametrize("count", range(2, 13))
def test_any_group_size_spans_five_to_one(count):
    # Distinct totals: performer 0 is best, the last performer is worst.
    scores = {pid: [count - pid] for pid in range(count)}
    points = task_points(scores)
    ordered = [points[pid] for pid in range(count)]
    assert ordered[0] == 5
    assert ordered[-1] == 1
    assert all(1 <= p <= 5 for p in ordered)
    assert ordered == sorted(ordered, reverse=True)  # a lower total never earns more points