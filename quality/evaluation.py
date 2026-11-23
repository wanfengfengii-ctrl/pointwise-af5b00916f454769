from dataclasses import dataclass

from device.take_history import TakenGroup
from profiles.versions import FrozenProfile
from quality.conversion import ConvertedReading, convert_reading
from quality.limits import LimitVerdict, judge_limit
from quality.units import verify_reading_unit


@dataclass(frozen=True, slots=True)
class QualityLine:
    measurement: ConvertedReading
    verdict: LimitVerdict


@dataclass(frozen=True, slots=True)
class QualityResult:
    group: TakenGroup
    lines: tuple[QualityLine, ...]


def evaluate_group(profile: FrozenProfile, group: TakenGroup) -> QualityResult:
    if group.binding.version_id != profile.version_id:
        raise ValueError('taken group refers to a different frozen profile')
    group.require_complete()
    if tuple(reading.channel for reading in group.readings) != profile.group.channels:
        raise ValueError('taken group does not cover the frozen channel list in order')

    lines = []
    for reading, rule in zip(group.readings, profile.group.rules, strict=True):
        verify_reading_unit(reading, rule)
        converted = convert_reading(reading, rule)
        lines.append(QualityLine(converted, judge_limit(converted, rule.threshold)))
    return QualityResult(group, tuple(lines))
