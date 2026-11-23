import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from capture.requests import CaptureRequest, require_same_request
from device.events import reading_from_row
from device.take_history import TakeBinding, TakenGroup


_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS capture_orders (
        capture_id TEXT PRIMARY KEY,
        shift_id TEXT NOT NULL,
        version_id INTEGER NOT NULL REFERENCES profile_versions(version_id),
        generations TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('pending', 'invalid', 'verified'))
    )''',
    '''CREATE TABLE IF NOT EXISTS verified_members (
        capture_id TEXT NOT NULL REFERENCES capture_orders(capture_id),
        position INTEGER NOT NULL,
        channel TEXT NOT NULL,
        generation INTEGER NOT NULL,
        event_id TEXT NOT NULL,
        raw_value TEXT NOT NULL,
        raw_unit TEXT NOT NULL,
        source TEXT NOT NULL,
        PRIMARY KEY (capture_id, position),
        UNIQUE (capture_id, channel)
    )''',
)


@dataclass(frozen=True, slots=True)
class CaptureOrder:
    request: CaptureRequest
    state: Literal['pending', 'invalid', 'verified']
    group: TakenGroup | None = None


def _open(path) -> sqlite3.Connection:
    uri = Path(path).resolve().as_uri() + '?mode=rw'
    db = sqlite3.connect(uri, uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    return db


def initialize_order_store(path) -> None:
    with closing(_open(path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        for statement in _SCHEMA:
            db.execute(statement)


def _read_order(db: sqlite3.Connection, capture_id: str) -> CaptureOrder | None:
    row = db.execute('SELECT * FROM capture_orders WHERE capture_id = ?', (capture_id,)).fetchone()
    if row is None:
        return None
    binding = TakeBinding(
        row['capture_id'], row['version_id'],
        tuple(tuple(member) for member in json.loads(row['generations'])),
    )
    request = CaptureRequest(row['shift_id'], binding)
    group = None
    if row['state'] == 'verified':
        rows = db.execute(
            'SELECT * FROM verified_members WHERE capture_id = ? ORDER BY position', (capture_id,)
        )
        group = TakenGroup(binding, tuple(reading_from_row(member) for member in rows))
        group.require_complete()
    return CaptureOrder(request, row['state'], group)


def _require_order(db: sqlite3.Connection, capture_id: str) -> CaptureOrder:
    order = _read_order(db, capture_id)
    if order is None:
        raise KeyError(capture_id)
    return order


def load_order(path, capture_id: str) -> CaptureOrder:
    with closing(_open(path)) as db, db:
        db.execute('BEGIN')
        return _require_order(db, capture_id)


def bind_request(path, request: CaptureRequest) -> CaptureOrder:
    binding = request.binding
    with closing(_open(path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        existing = _read_order(db, request.capture_id)
        if existing is not None:
            require_same_request(existing.request, request)
            return existing
        db.execute(
            '''INSERT INTO capture_orders (capture_id, shift_id, version_id, generations, state)
               VALUES (?, ?, ?, ?, 'pending')''',
            (request.capture_id, request.shift_id, binding.version_id, json.dumps(binding.generations)),
        )
        return CaptureOrder(request, 'pending')


def _record_settlement(path, settled: CaptureOrder) -> CaptureOrder:
    request = settled.request
    with closing(_open(path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        existing = _require_order(db, request.capture_id)
        require_same_request(existing.request, request)
        if existing.state != 'pending':
            if existing != settled:
                raise ValueError('settlement conflicts with a previously confirmed outcome')
            return existing
        if settled.group is not None:
            db.executemany(
                '''INSERT INTO verified_members
                   (capture_id, position, channel, generation, event_id, raw_value, raw_unit, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                [(request.capture_id, position, read.channel, read.generation, read.event_id,
                  hex(read.raw_value), read.raw_unit, read.source)
                 for position, read in enumerate(settled.group.readings)],
            )
        db.execute(
            'UPDATE capture_orders SET state = ? WHERE capture_id = ?',
            (settled.state, request.capture_id),
        )
        return settled


def mark_invalid(path, request: CaptureRequest) -> CaptureOrder:
    return _record_settlement(path, CaptureOrder(request, 'invalid'))


def save_verified_group(path, request: CaptureRequest, group: TakenGroup) -> CaptureOrder:
    if group.binding != request.binding:
        raise ValueError('verified group must have the original request binding')
    group.require_complete()
    return _record_settlement(path, CaptureOrder(request, 'verified', group))
