from contextlib import closing
from dataclasses import dataclass

from handover.archive import open_archive, read_capture_archive
from handover.receipt import FirstReceipt
from profiles.channels import require_label


@dataclass(frozen=True, slots=True)
class SignedLine:
    channel: str
    generation: int
    event_id: str
    source: str
    raw_value: int
    raw_unit: str
    converted_value: int
    target_unit: str
    threshold: int
    exceeded: bool


@dataclass(frozen=True, slots=True)
class SignedCapture:
    capture_id: str
    shift_id: str
    version_id: int
    lines: tuple[SignedLine, ...]
    receipt: FirstReceipt


def restore_signed_capture(record) -> SignedCapture:
    head, rows = record
    if not rows:
        raise ValueError('signed capture has no archived details')
    lines = tuple(
        SignedLine(
            row['channel'], row['generation'], row['event_id'], row['source'],
            int(row['raw_value'], 16), row['raw_unit'], int(row['converted_value'], 16),
            row['target_unit'], int(row['threshold'], 16), bool(row['exceeded']),
        )
        for row in rows
    )
    return SignedCapture(
        head['capture_id'], head['shift_id'], head['version_id'], lines,
        FirstReceipt(head['capture_id'], head['number']),
    )


def receive(path, capture_id: str) -> SignedCapture | None:
    require_label(capture_id, 'capture ID')
    with closing(open_archive(path)) as db, db:
        db.execute('BEGIN')
        record = read_capture_archive(db, capture_id)
        return None if record is None else restore_signed_capture(record)
