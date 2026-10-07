"""Small-sample paired bootstrap statistics for evaluation comparisons."""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class BootstrapResult:
    n: int
    mean_delta: float | None
    ci95_low: float | None
    ci95_high: float | None


def nearest_rank(values: Sequence[float], fraction: float) -> float:
    """Return the nearest-rank quantile of a non-empty sequence."""
    if not values:
        raise ValueError("values must not be empty")
    if not 0 <= fraction <= 1:
        raise ValueError("fraction must be between 0 and 1")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def paired_bootstrap(
    pairs: Sequence[tuple[float, float]], *, seed: int, repetitions: int
) -> BootstrapResult:
    """Bootstrap the mean of left minus right over paired items."""
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    if not pairs:
        return BootstrapResult(0, None, None, None)

    deltas = [left - right for left, right in pairs]
    rng = random.Random(seed)
    draws = [
        statistics.mean(deltas[rng.randrange(len(deltas))] for _ in deltas)
        for _ in range(repetitions)
    ]
    return BootstrapResult(
        n=len(deltas),
        mean_delta=statistics.mean(deltas),
        ci95_low=nearest_rank(draws, 0.025),
        ci95_high=nearest_rank(draws, 0.975),
    )
