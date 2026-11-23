import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from capture.intake import initialize_station, take_or_resume
from device.events import InstrumentEvent
from device.group_take import DeviceExchangeInterrupted
from device.latch import latch, read_active
from device.preview import GroupPreview, preview
from device.store import open_device_store
from profiles.channels import ChannelDefinition, ChannelRule
from profiles.versions import configure


CATALOG = (ChannelDefinition('X', 'count'), ChannelDefinition('Y', 'count'))
X_RULE = ChannelRule('X', 'count', 'μm/s', 2, 14)
Y_RULE = ChannelRule('Y', 'count', 'μm/s', 2, 14)


def lose_exchange(_):
    raise DeviceExchangeInterrupted('instrument link interrupted')


def reject_archive_commit(db):
    db.execute('PRAGMA temp_store = MEMORY')
    db.execute('CREATE TEMP TABLE publish_test_parent (id INTEGER PRIMARY KEY)')
    db.execute('''CREATE TEMP TABLE publish_test_child (
        parent_id INTEGER REFERENCES publish_test_parent(id) DEFERRABLE INITIALLY DEFERRED
    )''')
    db.execute('INSERT INTO publish_test_child VALUES (1)')


class StationCase(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix='vibration-tests-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.station = self.root / 'station.sqlite3'
        self.device = self.root / 'device.sqlite3'
        initialize_station(self.station, self.device, CATALOG)
        self.main = configure(self.station, '卷纸机', '联检', [X_RULE, Y_RULE])
        self.y_only = configure(self.station, '卷纸机', 'Y 复测', [Y_RULE])

    def load_pair(self):
        return (
            latch(self.device, InstrumentEvent('X', 'x-1', 7, 'instrument/01:1')),
            latch(self.device, InstrumentEvent('Y', 'y-1', 11, 'instrument/01:2')),
        )

    def snapshot(self, profile=None):
        if profile is None:
            profile = self.main
        snapshot = preview(self.station, self.device, profile.group_id)
        self.assertIsInstance(snapshot, GroupPreview)
        return snapshot

    def take(self, capture_id, snapshot, shift_id='甲班', *, offline=False, **hooks):
        return take_or_resume(
            self.station, None if offline else self.device, shift_id, capture_id,
            snapshot.profile.group_id, snapshot.generations, **hooks,
        )

    def active(self):
        with closing(open_device_store(self.device)) as db, db:
            db.execute('BEGIN')
            return read_active(db, ('X', 'Y'))

    def archive_counts(self, capture_id):
        with closing(sqlite3.connect(self.station)) as db, db:
            db.execute('BEGIN')
            head = db.execute(
                'SELECT COUNT(*) FROM signed_captures WHERE capture_id = ?', (capture_id,)
            ).fetchone()[0]
            lines = db.execute(
                'SELECT COUNT(*) FROM signed_lines WHERE capture_id = ?', (capture_id,)
            ).fetchone()[0]
            receipts = db.execute(
                'SELECT COUNT(*) FROM first_receipts WHERE capture_id = ?', (capture_id,)
            ).fetchone()[0]
        return head, lines, receipts
