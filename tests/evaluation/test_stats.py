"""Tests for the small-sample statistics the evaluation reports rely on.

Runs are few and non-deterministic, so a bare percentage would overstate certainty: every rate is
reported with a Wilson score interval, and latency with percentiles rather than a mean alone.
"""

import pytest

from multiagent.evaluation.stats import mean, percentile, wilson_interval


def test_wilson_interval_for_an_even_split():
    low, high = wilson_interval(5, 10)

    assert low == pytest.approx(0.237, abs=0.001)
    assert high == pytest.approx(0.763, abs=0.001)


def test_wilson_interval_does_not_collapse_to_zero_width_at_the_extremes():
    """The naive interval for 0/5 is [0, 0], claiming certainty from five runs."""
    low, high = wilson_interval(0, 5)
    assert low == 0.0
    assert high == pytest.approx(0.434, abs=0.001)

    low, high = wilson_interval(5, 5)
    assert low == pytest.approx(0.566, abs=0.001)
    assert high == 1.0


def test_wilson_interval_narrows_as_the_sample_grows():
    small = wilson_interval(5, 10)
    large = wilson_interval(50, 100)

    assert (large[1] - large[0]) < (small[1] - small[0])


def test_wilson_interval_is_undefined_for_no_samples():
    assert wilson_interval(0, 0) is None


def test_wilson_interval_rejects_impossible_counts():
    with pytest.raises(ValueError):
        wilson_interval(6, 5)
    with pytest.raises(ValueError):
        wilson_interval(-1, 5)


def test_percentile_interpolates_between_ranks():
    values = [1, 2, 3, 4, 5]

    assert percentile(values, 50) == 3
    assert percentile(values, 95) == pytest.approx(4.8)
    assert percentile(values, 0) == 1
    assert percentile(values, 100) == 5


def test_percentile_does_not_depend_on_input_order():
    assert percentile([5, 1, 4, 2, 3], 50) == 3


def test_percentile_of_a_single_value_is_that_value_and_of_nothing_is_none():
    assert percentile([7.5], 95) == 7.5
    assert percentile([], 50) is None


def test_mean_of_nothing_is_none():
    assert mean([1, 2, 3]) == 2
    assert mean([]) is None
