from dataclasses import dataclass
from typing import Iterable

from profiles.channels import ChannelRule, require_label
from profiles.groups import ChannelGroup, build_group
from profiles.store import insert_profile_version, load_channel_catalog


@dataclass(frozen=True, slots=True)
class FrozenProfile:
    version_id: int
    group_id: str
    name: str
    revision: int
    group: ChannelGroup


def configure(path, name: str, group_name: str, rules: Iterable[ChannelRule]) -> FrozenProfile:
    require_label(name, 'profile name')
    group = build_group(group_name, rules, load_channel_catalog(path))
    version_id, group_id, revision = insert_profile_version(path, name, group)
    return FrozenProfile(version_id, group_id, name, revision, group)
