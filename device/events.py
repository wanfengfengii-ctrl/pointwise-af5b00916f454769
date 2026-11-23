import sqlite3
from dataclasses import dataclass

from device.store import read_device_channel
from profiles.channels import require_label


@dataclass(frozen=True, slots=True)
class InstrumentEvent:
    channel: str
    event_id: str
    raw_value: int
    source: str


@dataclass(frozen=True, slots=True)
class LatchedReading:
    channel: str
    generation: int
    event_id: str
    raw_value: int
    raw_unit: str
    source: str

    def __post_init__(self) -> None:
        require_label(self.raw_unit, 'recorded raw unit')
        validate_instrument_event(InstrumentEvent(self.channel, self.event_id, self.raw_value, self.source))
        if type(self.generation) is not int or not 0 < self.generation < 2**63:
            raise ValueError('generation must be a positive SQLite integer')


def validate_instrument_event(event: InstrumentEvent) -> None:
    if not isinstance(event, InstrumentEvent):
        raise ValueError('an instrument event is required')
    require_label(event.channel, 'channel')
    require_label(event.event_id, 'instrument event ID')
    require_label(event.source, 'instrument source')
    if type(event.raw_value) is not int:
        raise ValueError('raw value must be an integer')


def reading_from_row(row: sqlite3.Row) -> LatchedReading:
    return LatchedReading(
        row['channel'], row['generation'], row['event_id'], int(row['raw_value'], 16),
        row['raw_unit'], row['source'],
    )


def find_event(db: sqlite3.Connection, channel: str, event_id: str) -> LatchedReading | None:
    row = db.execute(
        'SELECT * FROM instrument_events WHERE channel = ? AND event_id = ?', (channel, event_id)
    ).fetchone()
    return None if row is None else reading_from_row(row)


def record_event(db: sqlite3.Connection, event: InstrumentEvent) -> LatchedReading:
    definition = read_device_channel(db, event.channel)
    previous = db.execute(
        'SELECT MAX(generation) FROM instrument_events WHERE channel = ?', (event.channel,)
    ).fetchone()[0]
    generation = (previous or 0) + 1
    reading = LatchedReading(
        event.channel, generation, event.event_id, event.raw_value, definition.raw_unit, event.source
    )
    db.execute(
        '''INSERT INTO instrument_events (channel, generation, event_id, raw_value, raw_unit, source)
           VALUES (?, ?, ?, ?, ?, ?)''',
        (reading.channel, reading.generation, reading.event_id, hex(reading.raw_value),
         reading.raw_unit, reading.source),
    )
    return reading
