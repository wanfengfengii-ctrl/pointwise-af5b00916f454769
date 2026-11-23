import sqlite3
from contextlib import closing
from pathlib import Path


_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS signed_captures (
        capture_id TEXT PRIMARY KEY REFERENCES capture_orders(capture_id),
        shift_id TEXT NOT NULL,
        version_id INTEGER NOT NULL REFERENCES profile_versions(version_id)
    )''',
    '''CREATE INDEX IF NOT EXISTS signed_captures_by_shift
       ON signed_captures (shift_id, capture_id)''',
    '''CREATE TABLE IF NOT EXISTS signed_lines (
        capture_id TEXT NOT NULL REFERENCES signed_captures(capture_id),
        position INTEGER NOT NULL,
        channel TEXT NOT NULL,
        generation INTEGER NOT NULL,
        event_id TEXT NOT NULL,
        source TEXT NOT NULL,
        raw_value TEXT NOT NULL,
        raw_unit TEXT NOT NULL,
        converted_value TEXT NOT NULL,
        target_unit TEXT NOT NULL,
        threshold TEXT NOT NULL,
        exceeded INTEGER NOT NULL CHECK (exceeded IN (0, 1)),
        PRIMARY KEY (capture_id, position),
        UNIQUE (capture_id, channel)
    )''',
    '''CREATE TABLE IF NOT EXISTS first_receipts (
        capture_id TEXT PRIMARY KEY REFERENCES signed_captures(capture_id),
        number TEXT NOT NULL UNIQUE
    )''',
)


def open_archive(path) -> sqlite3.Connection:
    uri = Path(path).resolve().as_uri() + '?mode=rw'
    db = sqlite3.connect(uri, uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    return db


def initialize_archive(path) -> None:
    with closing(open_archive(path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        for statement in _SCHEMA:
            db.execute(statement)


def write_capture_archive(db: sqlite3.Connection, request, result, receipt) -> None:
    db.execute(
        'INSERT INTO signed_captures (capture_id, shift_id, version_id) VALUES (?, ?, ?)',
        (request.capture_id, request.shift_id, request.binding.version_id),
    )
    details = []
    for position, line in enumerate(result.lines):
        measurement = line.measurement
        original = measurement.original
        details.append((
            request.capture_id, position, original.channel, original.generation,
            original.event_id, original.source, hex(original.raw_value), original.raw_unit,
            hex(measurement.value), measurement.unit, hex(line.verdict.threshold),
            int(line.verdict.exceeded),
        ))
    db.executemany(
        '''INSERT INTO signed_lines
           (capture_id, position, channel, generation, event_id, source, raw_value, raw_unit,
            converted_value, target_unit, threshold, exceeded)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        details,
    )
    db.execute(
        'INSERT INTO first_receipts (capture_id, number) VALUES (?, ?)',
        (receipt.capture_id, receipt.number),
    )


def read_capture_archive(db: sqlite3.Connection, capture_id: str):
    head = db.execute(
        '''SELECT c.capture_id, c.shift_id, c.version_id, r.number
           FROM signed_captures AS c JOIN first_receipts AS r USING (capture_id)
           WHERE c.capture_id = ?''',
        (capture_id,),
    ).fetchone()
    if head is None:
        return None
    lines = db.execute(
        'SELECT * FROM signed_lines WHERE capture_id = ? ORDER BY position', (capture_id,)
    ).fetchall()
    return head, lines


def read_shift_archive(db: sqlite3.Connection, shift_id: str):
    ids = db.execute(
        '''SELECT c.capture_id FROM signed_captures AS c
           JOIN first_receipts AS r USING (capture_id)
           WHERE c.shift_id = ? ORDER BY c.capture_id''',
        (shift_id,),
    ).fetchall()
    return [read_capture_archive(db, row['capture_id']) for row in ids]
