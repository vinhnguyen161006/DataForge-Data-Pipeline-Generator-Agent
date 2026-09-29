from collections.abc import Callable

from pydantic import BaseModel


class TimingSamples(BaseModel):
    seconds: list[float]

    def median(self) -> float:
        """TODO: median of the samples."""
        raise NotImplementedError

    def relative_noise(self) -> float:
        """TODO: half the interquartile range divided by the median."""
        raise NotImplementedError


class SpeedVerdict(BaseModel):
    faster: bool
    baseline_median: float
    candidate_median: float
    relative_improvement: float
    required_improvement: float


def measure(fn: Callable[[], object], repeats: int, warmup: int = 1) -> TimingSamples:
    """TODO: run warmup iterations, then time `repeats` runs with perf_counter."""
    raise NotImplementedError


def is_faster(
    baseline: TimingSamples, candidate: TimingSamples, min_relative_improvement: float
) -> SpeedVerdict:
    """TODO: faster only if median improvement exceeds both the threshold and measured noise."""
    raise NotImplementedError
