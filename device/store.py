import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Iterable

from profiles.channels import ChannelDefinition


_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS device_channels (
        channel TEXT PRIMARY KEY,
        raw_unit TEXT NOT NULL
    )''',
    '''CREATE TABLE IF NOT EXISTS instrument_events (
        channel TEXT NOT NULL REFERENCES device_channels(channel),
        generation INTEGER NOT NULL CHECK (generation > 0),
        event_id TEXT NOT NULL,
        raw_value TEXT NOT NULL,
        raw_unit TEXT NOT NULL,
        source TEXT NOT NULL,
        PRIMARY KEY (channel, generation),
        UNIQUE (channel, event_id)
    )''',
    '''CREATE TABLE IF NOT EXISTS active_latches (
        channel TEXT PRIMARY KEY,
        generation INTEGER NOT NULL,
        FOREIGN KEY (channel, generation) REFERENCES instrument_events(channel, generation)
    )''',
    '''CREATE TABLE IF NOT EXISTS take_records (
        capture_id TEXT PRIMARY KEY,
        version_id INTEGER NOT NULL,
        generations TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('invalid', 'taken'))
    )''',
    '''CREATE TABLE IF NOT EXISTS take_members (
        capture_id TEXT NOT NULL REFERENCES take_records(capture_id),
        position INTEGER NOT NULL,
        channel TEXT NOT NULL,
        generation INTEGER NOT NULL,
        PRIMARY KEY (capture_id, position),
        UNIQUE (channel, generation),
        FOREIGN KEY (channel, generation) REFERENCES instrument_events(channel, generation)
    )''',
)


def _configure(db: sqlite3.Connection) -> sqlite3.Connection:
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    return db


def open_device_store(path) -> sqlite3.Connection:
    uri = Path(path).resolve().as_uri() + '?mode=rw'
    return _configure(sqlite3.connect(uri, uri=True))


def initialize_device_store(path, channels: Iterable[ChannelDefinition]) -> None:
    catalog = {}
    for definition in channels:
        if not isinstance(definition, ChannelDefinition) or definition.channel in catalog:
            raise ValueError('device catalog requires unique channel definitions')
        catalog[definition.channel] = definition.raw_unit
    if not catalog:
        raise ValueError('device catalog must contain at least one channel')
    with closing(_configure(sqlite3.connect(path))) as db, db:
        db.execute('BEGIN IMMEDIATE')
        for statement in _SCHEMA:
            db.execute(statement)
        registered = dict(db.execute('SELECT channel, raw_unit FROM device_channels'))
        if registered:
            if registered != catalog:
                raise ValueError('device catalog differs from the station catalog')
        else:
            db.executemany(
                'INSERT INTO device_channels (channel, raw_unit) VALUES (?, ?)', catalog.items()
            )


def read_device_channel(db: sqlite3.Connection, channel: str) -> ChannelDefinition:
    row = db.execute(
        'SELECT raw_unit FROM device_channels WHERE channel = ?', (channel,)
    ).fetchone()
    if row is None:
        raise ValueError(f'unknown device channel {channel!r}')
    return ChannelDefinition(channel, row['raw_unit'])
