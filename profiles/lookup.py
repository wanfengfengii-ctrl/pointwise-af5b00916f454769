from profiles.channels import ChannelRule, require_label
from profiles.groups import ChannelGroup
from profiles.store import read_profile_by_group, read_profile_version
from profiles.versions import FrozenProfile


def _restore(header, rows) -> FrozenProfile:
    rules = tuple(
        ChannelRule(
            row['channel'], row['raw_unit'], row['target_unit'],
            int(row['multiplier'], 16), int(row['threshold'], 16),
        )
        for row in rows
    )
    if not rules:
        raise ValueError('frozen profile has no stored rules')
    return FrozenProfile(
        header['version_id'], header['group_id'], header['profile_name'],
        header['revision'], ChannelGroup(header['group_name'], rules),
    )


def load_frozen_profile(path, version_id: int) -> FrozenProfile:
    if type(version_id) is not int or not 0 < version_id < 2**63:
        raise ValueError('version ID must be a positive SQLite integer')
    return _restore(*read_profile_version(path, version_id))


def resolve_frozen_group(path, group_id: str) -> FrozenProfile:
    require_label(group_id, 'frozen group ID')
    return _restore(*read_profile_by_group(path, group_id))
