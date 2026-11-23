from dataclasses import dataclass
from typing import Mapping


def require_label(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} must be a nonempty string')
    return value


@dataclass(frozen=True, slots=True)
class ChannelDefinition:
    channel: str
    raw_unit: str

    def __post_init__(self) -> None:
        require_label(self.channel, 'channel')
        require_label(self.raw_unit, 'raw unit')


@dataclass(frozen=True, slots=True)
class ChannelRule:
    channel: str
    raw_unit: str
    target_unit: str
    multiplier: int
    threshold: int


def validate_channel_rule(
    rule: ChannelRule, catalog: Mapping[str, ChannelDefinition]
) -> None:
    if not isinstance(rule, ChannelRule):
        raise ValueError('a channel rule is required')
    require_label(rule.channel, 'channel')
    require_label(rule.raw_unit, 'raw unit')
    require_label(rule.target_unit, 'target unit')
    definition = catalog.get(rule.channel)
    if definition is None:
        raise ValueError(f'unknown channel {rule.channel!r}')
    if rule.raw_unit != definition.raw_unit:
        raise ValueError(f'raw unit differs from the catalog for {rule.channel!r}')
    if type(rule.multiplier) is not int or rule.multiplier <= 0:
        raise ValueError('multiplier must be a positive integer')
    if type(rule.threshold) is not int:
        raise ValueError('threshold must be an integer')
