import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Iterable

from profiles.channels import ChannelDefinition
from profiles.groups import ChannelGroup


_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS channel_catalog (
        channel TEXT PRIMARY KEY,
        raw_unit TEXT NOT NULL
    )''',
    '''CREATE TABLE IF NOT EXISTS profile_versions (
        version_id INTEGER PRIMARY KEY,
        group_id TEXT NOT NULL UNIQUE,
        profile_name TEXT NOT NULL,
        group_name TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK (revision > 0),
        UNIQUE (profile_name, group_name, revision)
    )''',
    '''CREATE TABLE IF NOT EXISTS profile_rules (
        version_id INTEGER NOT NULL REFERENCES profile_versions(version_id),
        position INTEGER NOT NULL,
        channel TEXT NOT NULL REFERENCES channel_catalog(channel),
        raw_unit TEXT NOT NULL,
        target_unit TEXT NOT NULL,
        multiplier TEXT NOT NULL,
        threshold TEXT NOT NULL,
        PRIMARY KEY (version_id, position),
        UNIQUE (version_id, channel)
    )''',
)


def _open(path, *, create: bool = False) -> sqlite3.Connection:
    if create:
        db = sqlite3.connect(path)
    else:
        db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=rw', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    return db


def _catalog(db: sqlite3.Connection) -> dict[str, ChannelDefinition]:
    rows = db.execute('SELECT channel, raw_unit FROM channel_catalog ORDER BY channel')
    return {row['channel']: ChannelDefinition(row['channel'], row['raw_unit']) for row in rows}


def initialize_profile_store(
    path, channels: Iterable[ChannelDefinition]
) -> tuple[ChannelDefinition, ...]:
    with closing(_open(path, create=True)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        for statement in _SCHEMA:
            db.execute(statement)
        catalog = _catalog(db)
        if not catalog:
            for definition in channels:
                if not isinstance(definition, ChannelDefinition):
                    raise ValueError('a channel definition is required')
                if definition.channel in catalog:
                    raise ValueError(f'duplicate catalog channel {definition.channel!r}')
                catalog[definition.channel] = definition
            if not catalog:
                raise ValueError('station catalog must contain at least one channel')
            db.executemany(
                'INSERT INTO channel_catalog (channel, raw_unit) VALUES (?, ?)',
                [(item.channel, item.raw_unit) for item in catalog.values()],
            )
        return tuple(catalog[name] for name in sorted(catalog))


def load_channel_catalog(path) -> dict[str, ChannelDefinition]:
    with closing(_open(path)) as db:
        return _catalog(db)


def insert_profile_version(path, name: str, group: ChannelGroup) -> tuple[int, str, int]:
    with closing(_open(path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        version_id = db.execute(
            'SELECT COALESCE(MAX(version_id), 0) + 1 FROM profile_versions'
        ).fetchone()[0]
        revision = db.execute(
            '''SELECT COALESCE(MAX(revision), 0) + 1 FROM profile_versions
               WHERE profile_name = ? AND group_name = ?''',
            (name, group.name),
        ).fetchone()[0]
        group_id = f'group-{version_id}'
        db.execute(
            '''INSERT INTO profile_versions
               (version_id, group_id, profile_name, group_name, revision)
               VALUES (?, ?, ?, ?, ?)''',
            (version_id, group_id, name, group.name, revision),
        )
        db.executemany(
            '''INSERT INTO profile_rules
               (version_id, position, channel, raw_unit, target_unit, multiplier, threshold)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            [
                (version_id, position, rule.channel, rule.raw_unit, rule.target_unit,
                 hex(rule.multiplier), hex(rule.threshold))
                for position, rule in enumerate(group.rules)
            ],
        )
        return version_id, group_id, revision


def _read_profile(path, selector: str, identifier):
    with closing(_open(path)) as db, db:
        db.execute('BEGIN')
        header = db.execute(selector, (identifier,)).fetchone()
        if header is None:
            raise KeyError(identifier)
        rules = db.execute(
            'SELECT * FROM profile_rules WHERE version_id = ? ORDER BY position',
            (header['version_id'],),
        ).fetchall()
        return header, rules


def read_profile_version(path, version_id: int):
    return _read_profile(path, 'SELECT * FROM profile_versions WHERE version_id = ?', version_id)


def read_profile_by_group(path, group_id: str):
    return _read_profile(path, 'SELECT * FROM profile_versions WHERE group_id = ?', group_id)
