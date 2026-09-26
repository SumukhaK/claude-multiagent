"""Small-sample statistics for the evaluation report.

Runs are few (a local 1.5B model on a laptop is slow) and non-deterministic, so a bare
percentage would overstate certainty. Rates get a Wilson score interval, which — unlike the naive
normal approximation — doesn't collapse to a zero-width interval at 0/n or n/n.
"""

import math
from collections.abc import Sequence


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson score interval for a proportion (default 95%), or None if there are no samples."""
    if n < 0 or successes < 0 or successes > n:
        raise ValueError(f"impossible counts: {successes} successes out of {n}")
    if n == 0:
        return None
    p = successes / n
    denominator = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denominator
    margin = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def percentile(values: Sequence[float], q: float) -> float | None:
    """The q-th percentile (0-100) by linear interpolation, or None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None
