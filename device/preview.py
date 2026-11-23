from contextlib import closing
from dataclasses import dataclass

from device.events import LatchedReading
from device.latch import read_active
from device.store import open_device_store
from profiles.lookup import resolve_frozen_group
from profiles.versions import FrozenProfile


@dataclass(frozen=True, slots=True)
class GroupPreview:
    profile: FrozenProfile
    readings: tuple[LatchedReading, ...]

    @property
    def generations(self) -> tuple[tuple[str, int], ...]:
        return tuple((row.channel, row.generation) for row in self.readings)


@dataclass(frozen=True, slots=True)
class PreviewPending:
    profile: FrozenProfile
    missing: tuple[str, ...]


def preview(station_path, device_path, group_id: str) -> GroupPreview | PreviewPending:
    profile = resolve_frozen_group(station_path, group_id)
    channels = profile.group.channels
    with closing(open_device_store(device_path)) as db, db:
        db.execute('BEGIN')
        active = read_active(db, channels)
    missing = tuple(channel for channel in channels if channel not in active)
    if missing:
        return PreviewPending(profile, missing)
    return GroupPreview(profile, tuple(active[channel] for channel in channels))
