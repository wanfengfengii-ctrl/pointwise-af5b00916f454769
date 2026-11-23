import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import Literal

from device.events import LatchedReading, reading_from_row
from device.store import open_device_store
from profiles.channels import require_label


@dataclass(frozen=True, slots=True)
class TakeBinding:
    capture_id: str
    version_id: int
    generations: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        require_label(self.capture_id, 'capture ID')
        if type(self.version_id) is not int or not 0 < self.version_id < 2**63:
            raise ValueError('version ID must be a positive SQLite integer')
        if not isinstance(self.generations, tuple) or not self.generations:
            raise ValueError('a nonempty generation tuple is required')
        seen = set()
        for member in self.generations:
            if not isinstance(member, tuple) or len(member) != 2:
                raise ValueError('expected a channel and generation pair')
            channel, generation = member
            require_label(channel, 'bound channel')
            if channel in seen:
                raise ValueError(f'duplicate bound channel {channel!r}')
            if type(generation) is not int or not 0 < generation < 2**63:
                raise ValueError('generation must be a positive SQLite integer')
            seen.add(channel)


@dataclass(frozen=True, slots=True)
class TakenGroup:
    binding: TakeBinding
    readings: tuple[LatchedReading, ...]

    def require_complete(self) -> None:
        actual = tuple((reading.channel, reading.generation) for reading in self.readings)
        if actual != self.binding.generations:
            raise ValueError('actual take members differ from the bound group')


@dataclass(frozen=True, slots=True)
class DeviceOutcome:
    binding: TakeBinding
    state: Literal['pending', 'invalid', 'taken']
    group: TakenGroup | None = None


def read_take_record(db: sqlite3.Connection, binding: TakeBinding) -> DeviceOutcome:
    record = db.execute(
        'SELECT * FROM take_records WHERE capture_id = ?', (binding.capture_id,)
    ).fetchone()
    if record is None:
        return DeviceOutcome(binding, 'pending')
    stored = TakeBinding(
        record['capture_id'], record['version_id'],
        tuple(tuple(member) for member in json.loads(record['generations'])),
    )
    if stored != binding:
        raise ValueError('device capture ID has a different take binding')
    if record['state'] == 'invalid':
        return DeviceOutcome(stored, 'invalid')
    rows = db.execute(
        '''SELECT e.* FROM take_members AS m
           JOIN instrument_events AS e USING (channel, generation)
           WHERE m.capture_id = ? ORDER BY m.position''',
        (stored.capture_id,),
    )
    group = TakenGroup(stored, tuple(reading_from_row(row) for row in rows))
    group.require_complete()
    return DeviceOutcome(stored, 'taken', group)


def write_take_record(db: sqlite3.Connection, outcome: DeviceOutcome) -> None:
    binding = outcome.binding
    group = outcome.group
    if outcome.state == 'taken':
        if group is None or group.binding != binding:
            raise ValueError('a taken outcome requires its own actual group')
        group.require_complete()
    elif outcome.state != 'invalid' or group is not None:
        raise ValueError('only terminal device outcomes can be stored')
    db.execute(
        '''INSERT INTO take_records (capture_id, version_id, generations, state)
           VALUES (?, ?, ?, ?)''',
        (binding.capture_id, binding.version_id, json.dumps(binding.generations), outcome.state),
    )
    if group is not None:
        db.executemany(
            '''INSERT INTO take_members (capture_id, position, channel, generation)
               VALUES (?, ?, ?, ?)''',
            [(binding.capture_id, position, row.channel, row.generation)
             for position, row in enumerate(group.readings)],
        )


def device_outcome(path, binding: TakeBinding) -> DeviceOutcome:
    with closing(open_device_store(path)) as db, db:
        db.execute('BEGIN')
        return read_take_record(db, binding)
