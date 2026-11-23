from dataclasses import dataclass

from device.events import LatchedReading
from profiles.channels import ChannelRule


@dataclass(frozen=True, slots=True)
class ConvertedReading:
    original: LatchedReading
    value: int
    unit: str


def convert_reading(reading: LatchedReading, rule: ChannelRule) -> ConvertedReading:
    return ConvertedReading(reading, reading.raw_value * rule.multiplier, rule.target_unit)
