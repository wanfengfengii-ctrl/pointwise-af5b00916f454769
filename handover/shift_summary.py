from contextlib import closing
from dataclasses import dataclass

from handover.archive import open_archive, read_shift_archive
from handover.lookup import restore_signed_capture
from profiles.channels import require_label


@dataclass(frozen=True, slots=True)
class ShiftSummary:
    shift_id: str
    group_count: int
    exceedances: dict[str, int]
    sources: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]


def shift(path, shift_id: str) -> ShiftSummary:
    require_label(shift_id, 'shift ID')
    with closing(open_archive(path)) as db, db:
        db.execute('BEGIN')
        records = read_shift_archive(db, shift_id)
    exceedances = {}
    sources = []
    for record in records:
        signed = restore_signed_capture(record)
        sources.append((signed.capture_id, tuple((line.channel, line.source) for line in signed.lines)))
        for line in signed.lines:
            exceedances[line.channel] = exceedances.get(line.channel, 0) + int(line.exceeded)
    return ShiftSummary(shift_id, len(records), dict(sorted(exceedances.items())), tuple(sources))
