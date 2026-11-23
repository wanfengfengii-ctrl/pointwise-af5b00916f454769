from dataclasses import dataclass
from typing import Iterable, Mapping

from profiles.channels import ChannelDefinition, ChannelRule, require_label, validate_channel_rule


@dataclass(frozen=True, slots=True)
class ChannelGroup:
    name: str
    rules: tuple[ChannelRule, ...]

    @property
    def channels(self) -> tuple[str, ...]:
        return tuple(rule.channel for rule in self.rules)


def build_group(
    name: str, rules: Iterable[ChannelRule], catalog: Mapping[str, ChannelDefinition]
) -> ChannelGroup:
    require_label(name, 'group name')
    ordered = tuple(rules)
    if not ordered:
        raise ValueError('a group must contain at least one channel')
    seen = set()
    for rule in ordered:
        validate_channel_rule(rule, catalog)
        if rule.channel in seen:
            raise ValueError(f'duplicate group channel {rule.channel!r}')
        seen.add(rule.channel)
    return ChannelGroup(name, ordered)
