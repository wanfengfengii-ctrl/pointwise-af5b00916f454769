from capture.intake import initialize_station
from device.events import InstrumentEvent
from device.latch import latch
from handover.lookup import receive
from handover.shift_summary import ShiftSummary, shift
from profiles.channels import ChannelRule
from profiles.lookup import resolve_frozen_group
from profiles.versions import configure
from tests.support import CATALOG, StationCase, X_RULE, Y_RULE


class HandoverTests(StationCase):
    def test_closed_device_shift_review(self):
        self.load_pair()
        old = self.snapshot()
        signed = self.take('A', old)
        self.assertEqual(self.take('A', old), signed)
        configure(self.station, '卷纸机', '联检', (
            ChannelRule('Y', 'count', 'μm/s', 5, 60), X_RULE,
        ))
        self.device.rename(self.root / 'offline.sqlite3')
        self.assertEqual(receive(self.station, 'A'), signed)
        self.assertEqual(self.take('A', old, offline=True).receipt.number, 'R/A')
        self.assertEqual([line.converted_value for line in signed.lines], [14, 22])
        self.assertEqual(shift(self.station, '甲班'), ShiftSummary(
            '甲班', 1, {'X': 0, 'Y': 1},
            (('A', (('X', 'instrument/01:1'), ('Y', 'instrument/01:2'))),),
        ))

    def test_multiple_groups(self):
        self.load_pair()
        self.take('Z-last', self.snapshot())
        latch(self.device, InstrumentEvent('X', 'x-2', 12, 'instrument/02:1'))
        latch(self.device, InstrumentEvent('Y', 'y-2', 5, 'instrument/02:2'))
        reverse = configure(self.station, '卷纸机', '逆序巡检', [Y_RULE, X_RULE])
        self.take('A-first', self.snapshot(reverse))
        latch(self.device, InstrumentEvent('Y', 'y-3', 20, 'instrument/03:2'))
        self.take('B-other', self.snapshot(self.y_only), '乙班')
        self.device.rename(self.root / 'offline.sqlite3')
        self.assertEqual(shift(self.station, '甲班'), ShiftSummary(
            '甲班', 2, {'X': 1, 'Y': 1},
            (('A-first', (('Y', 'instrument/02:2'), ('X', 'instrument/02:1'))),
             ('Z-last', (('X', 'instrument/01:1'), ('Y', 'instrument/01:2')))),
        ))
        self.assertEqual(shift(self.station, '乙班'), ShiftSummary(
            '乙班', 1, {'Y': 1}, (('B-other', (('Y', 'instrument/03:2'),)),),
        ))

    def test_empty_shift(self):
        self.load_pair()
        self.take('A', self.snapshot())
        self.assertEqual(shift(self.station, '空班'), ShiftSummary('空班', 0, {}, ()))
        self.assertIsNone(receive(self.station, 'unknown'))

    def test_repeat_init(self):
        self.load_pair()
        old = self.snapshot()
        signed = self.take('A', old)
        newer = configure(self.station, '卷纸机', '联检', [Y_RULE, X_RULE])
        initialize_station(self.station, self.device, CATALOG)
        self.device.rename(self.root / 'offline.sqlite3')
        self.assertEqual(resolve_frozen_group(self.station, newer.group_id), newer)
        self.assertEqual(self.take('A', old, offline=True), signed)
        self.assertEqual(receive(self.station, 'A'), signed)
        self.assertEqual(shift(self.station, '甲班').group_count, 1)
        self.assertEqual(self.archive_counts('A'), (1, 2, 1))
