import sqlite3
from contextlib import closing
from typing import Iterable

from device.events import InstrumentEvent, LatchedReading, find_event, reading_from_row
from device.events import record_event, validate_instrument_event
from device.store import open_device_store


def latch(path, event: InstrumentEvent) -> LatchedReading:
    validate_instrument_event(event)
    with closing(open_device_store(path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        previous = find_event(db, event.channel, event.event_id)
        if previous is not None:
            if (previous.raw_value, previous.source) != (event.raw_value, event.source):
                raise ValueError('instrument event ID reused with different input')
            return previous
        reading = record_event(db, event)
        db.execute(
            '''INSERT INTO active_latches (channel, generation) VALUES (?, ?)
               ON CONFLICT(channel) DO UPDATE SET generation = excluded.generation''',
            (reading.channel, reading.generation),
        )
        return reading


def read_active(
    db: sqlite3.Connection, channels: Iterable[str]
) -> dict[str, LatchedReading]:
    active = {}
    for channel in channels:
        row = db.execute(
            '''SELECT e.* FROM active_latches AS a
               JOIN instrument_events AS e USING (channel, generation)
               WHERE a.channel = ?''',
            (channel,),
        ).fetchone()
        if row is not None:
            active[channel] = reading_from_row(row)
    return active


def clear_active_generations(
    db: sqlite3.Connection, generations: tuple[tuple[str, int], ...]
) -> None:
    deleted = db.executemany(
        'DELETE FROM active_latches WHERE channel = ? AND generation = ?', generations
    ).rowcount
    if deleted != len(generations):
        raise RuntimeError('the checked group changed inside the device transaction')
