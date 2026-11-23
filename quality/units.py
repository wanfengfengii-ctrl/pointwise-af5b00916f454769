from device.events import LatchedReading
from profiles.channels import ChannelRule


class UnitMismatch(ValueError):
    """A recorded unit differs from the frozen rule for that channel."""


def verify_reading_unit(reading: LatchedReading, rule: ChannelRule) -> None:
    if reading.channel != rule.channel:
        raise ValueError('reading and rule refer to different channels')
    if reading.raw_unit != rule.raw_unit:
        raise UnitMismatch(
            f'{reading.channel}: recorded {reading.raw_unit!r}, expected {rule.raw_unit!r}'
        )
