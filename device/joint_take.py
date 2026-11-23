"""Two-phase joint takes on one recorder: hold members, then take or release."""
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import Literal

from device.events import reading_from_row
from device.latch import read_active
from device.store import open_device_store
from device.take_history import TakeBinding, TakenGroup

JOINT_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS joint_records (
        capture_id TEXT PRIMARY KEY,
        version_id INTEGER NOT NULL,
        generations TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('prepared', 'taken', 'aborted', 'invalid'))
    )''',
    '''CREATE TABLE IF NOT EXISTS joint_holds (
        capture_id TEXT NOT NULL REFERENCES joint_records(capture_id),
        position INTEGER NOT NULL,
        channel TEXT NOT NULL,
        generation INTEGER NOT NULL,
        PRIMARY KEY (capture_id, position),
        UNIQUE (channel, generation),
        FOREIGN KEY (channel, generation) REFERENCES instrument_events(channel, generation)
    )''',
    '''CREATE TABLE IF NOT EXISTS joint_taken_members (
        capture_id TEXT NOT NULL REFERENCES joint_records(capture_id),
        position INTEGER NOT NULL,
        channel TEXT NOT NULL,
        generation INTEGER NOT NULL,
        PRIMARY KEY (capture_id, position),
        UNIQUE (channel, generation),
        FOREIGN KEY (channel, generation) REFERENCES instrument_events(channel, generation)
    )''',
)


@dataclass(frozen=True, slots=True)
class JointOutcome:
    binding: TakeBinding
    state: Literal['pending', 'invalid', 'prepared', 'taken', 'aborted']
    group: TakenGroup | None = None

    def __post_init__(self) -> None:
        if self.state == 'taken':
            if self.group is None or self.group.binding != self.binding:
                raise ValueError('a taken joint outcome requires its own actual group')
            self.group.require_complete()
        elif self.group is not None:
            raise ValueError('only a taken joint outcome carries a group')


def ensure_joint_schema(db: sqlite3.Connection) -> None:
    for statement in JOINT_SCHEMA:
        db.execute(statement)


def read_joint_record(db: sqlite3.Connection, binding: TakeBinding) -> JointOutcome:
    record = db.execute(
        'SELECT * FROM joint_records WHERE capture_id = ?', (binding.capture_id,)
    ).fetchone()
    if record is None:
        return JointOutcome(binding, 'pending')
    stored = TakeBinding(
        record['capture_id'], record['version_id'],
        tuple(tuple(member) for member in json.loads(record['generations'])),
    )
    if stored != binding:
        raise ValueError('device capture ID has a different joint binding')
    if record['state'] == 'taken':
        rows = db.execute(
            '''SELECT e.* FROM joint_taken_members AS m
               JOIN instrument_events AS e USING (channel, generation)
               WHERE m.capture_id = ? ORDER BY m.position''',
            (stored.capture_id,),
        )
        group = TakenGroup(stored, tuple(reading_from_row(row) for row in rows))
        return JointOutcome(stored, 'taken', group)
    return JointOutcome(stored, record['state'])


def held_generations(
    db: sqlite3.Connection, generations: tuple[tuple[str, int], ...]
) -> frozenset[tuple[str, int]]:
    held = set()
    for channel, generation in generations:
        row = db.execute(
            'SELECT 1 FROM joint_holds WHERE channel = ? AND generation = ?',
            (channel, generation),
        ).fetchone()
        if row is not None:
            held.add((channel, generation))
    return frozenset(held)


def prepare(path, binding: TakeBinding) -> JointOutcome:
    with closing(open_device_store(path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        ensure_joint_schema(db)
        outcome = read_joint_record(db, binding)
        if outcome.state != 'pending':
            return outcome
        channels = tuple(channel for channel, _ in binding.generations)
        active = read_active(db, channels)
        actual = tuple((row.channel, row.generation) for row in active.values())
        available = actual == binding.generations and not held_generations(db, binding.generations)
        outcome = JointOutcome(binding, 'prepared' if available else 'invalid')
        db.execute(
            '''INSERT INTO joint_records (capture_id, version_id, generations, state)
               VALUES (?, ?, ?, ?)''',
            (binding.capture_id, binding.version_id, json.dumps(binding.generations), outcome.state),
        )
        if outcome.state == 'prepared':
            db.executemany(
                '''INSERT INTO joint_holds (capture_id, position, channel, generation)
                   VALUES (?, ?, ?, ?)''',
                [(binding.capture_id, position, channel, generation)
                 for position, (channel, generation) in enumerate(binding.generations)],
            )
        return outcome


def commit(path, binding: TakeBinding) -> JointOutcome:
    with closing(open_device_store(path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        ensure_joint_schema(db)
        outcome = read_joint_record(db, binding)
        if outcome.state != 'prepared':
            return outcome
        rows = db.execute(
            '''SELECT e.* FROM joint_holds AS h
               JOIN instrument_events AS e USING (channel, generation)
               WHERE h.capture_id = ? ORDER BY h.position''',
            (binding.capture_id,),
        )
        outcome = JointOutcome(
            binding, 'taken', TakenGroup(binding, tuple(reading_from_row(row) for row in rows))
        )
        db.executemany(
            '''INSERT INTO joint_taken_members (capture_id, position, channel, generation)
               VALUES (?, ?, ?, ?)''',
            [(binding.capture_id, position, channel, generation)
             for position, (channel, generation) in enumerate(binding.generations)],
        )
        # Clear only latches still pointing at the held generations; newer
        # generations that arrived during the hold must stay active.
        db.executemany(
            'DELETE FROM active_latches WHERE channel = ? AND generation = ?', binding.generations
        )
        db.execute('DELETE FROM joint_holds WHERE capture_id = ?', (binding.capture_id,))
        db.execute(
            'UPDATE joint_records SET state = ? WHERE capture_id = ?',
            ('taken', binding.capture_id),
        )
        return outcome


def abort(path, binding: TakeBinding) -> JointOutcome:
    with closing(open_device_store(path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        ensure_joint_schema(db)
        outcome = read_joint_record(db, binding)
        if outcome.state != 'prepared':
            return outcome
        # Releasing the hold never touches active latches: an unreplaced
        # reading regains ordinary qualification, a replaced one stays gone.
        db.execute('DELETE FROM joint_holds WHERE capture_id = ?', (binding.capture_id,))
        db.execute(
            'UPDATE joint_records SET state = ? WHERE capture_id = ?',
            ('aborted', binding.capture_id),
        )
        return JointOutcome(binding, 'aborted')


def status(path, binding: TakeBinding) -> JointOutcome:
    with closing(open_device_store(path)) as db, db:
        db.execute('BEGIN')
        ensure_joint_schema(db)
        return read_joint_record(db, binding)
