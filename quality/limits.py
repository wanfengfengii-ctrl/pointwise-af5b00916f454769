from dataclasses import dataclass

from quality.conversion import ConvertedReading


@dataclass(frozen=True, slots=True)
class LimitVerdict:
    threshold: int
    exceeded: bool


def judge_limit(reading: ConvertedReading, threshold: int) -> LimitVerdict:
    return LimitVerdict(threshold, reading.value > threshold)
