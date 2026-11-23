from contextlib import closing

from capture.intake import take_or_resume
from capture.order_store import load_order
from capture.resume import CaptureStatus
from device.events import InstrumentEvent
from device.latch import latch
from device.store import open_device_store
from device.take_history import TakeBinding, device_outcome
from handover.lookup import receive
from handover.shift_summary import shift
from profiles.channels import ChannelRule
from profiles.versions import configure
from quality.units import UnitMismatch
from tests.support import StationCase


class CaptureTests(StationCase):
    def test_exact_threshold(self):
        self.load_pair()
        taken = self.take('A', self.snapshot())
        self.assertEqual([(row.raw_value, row.converted_value, row.exceeded) for row in taken.lines],
                         [(7, 14, False), (11, 22, True)])
        self.assertEqual(self.active(), {})
        self.assertEqual(receive(self.station, 'A'), taken)
        self.assertEqual(self.archive_counts('A'), (1, 2, 1))
        self.assertEqual(shift(self.station, '甲班').exceedances, {'X': 0, 'Y': 1})

    def test_exact_signed_integers(self):
        negative = -(1 << 100)
        positive = 1 << 95
        profile = configure(self.station, '卷纸机', '精确值', (
            ChannelRule('X', 'count', 'μm/s', 3, -(1 << 101) - (1 << 100)),
            ChannelRule('Y', 'count', 'μm/s', 1 << 70, (1 << 165) - 1),
        ))
        latch(self.device, InstrumentEvent('X', 'big-x', negative, 'large/01:1'))
        latch(self.device, InstrumentEvent('Y', 'big-y', positive, 'large/01:2'))
        taken = self.take('large', self.snapshot(profile))
        expected = [(negative, -(1 << 101) - (1 << 100), False), (positive, 1 << 165, True)]
        self.assertEqual([(line.raw_value, line.converted_value, line.exceeded) for line in taken.lines], expected)
        self.assertEqual(receive(self.station, 'large'), taken)
        self.assertEqual(shift(self.station, '甲班').exceedances, {'X': 0, 'Y': 1})

    def test_unit_consistency(self):
        self.load_pair()
        first = self.take('good', self.snapshot())
        self.assertEqual([(row.raw_unit, row.target_unit) for row in first.lines],
                         [('count', 'μm/s'), ('count', 'μm/s')])
        latch(self.device, InstrumentEvent('X', 'x-2', 7, 'instrument/02:1'))
        y = latch(self.device, InstrumentEvent('Y', 'y-2', 11, 'instrument/02:2'))
        snapshot = self.snapshot()
        # Simulate an input adapter that persisted inconsistent source-unit evidence.
        with closing(open_device_store(self.device)) as db, db:
            db.execute('UPDATE instrument_events SET raw_unit = ? WHERE channel = ? AND generation = ?',
                       ('mV', 'Y', y.generation))
        with self.assertRaises(UnitMismatch):
            self.take('bad-unit', snapshot)
        self.assertIsNone(receive(self.station, 'bad-unit'))
        self.assertEqual(self.archive_counts('bad-unit'), (0, 0, 0))
        self.assertEqual(shift(self.station, '甲班').group_count, 1)

    def _check_overlap(self, replacement_value):
        x, y = self.load_pair()
        stale = self.snapshot()
        replacement = []

        def collect_other(binding):
            self.assertEqual(load_order(self.station, binding.capture_id).state, 'pending')
            second = self.take('B', self.snapshot(self.y_only), '乙班')
            self.assertEqual([(line.channel, line.raw_value, line.source) for line in second.lines],
                             [('Y', 11, 'instrument/01:2')])
            replacement.append(latch(
                self.device, InstrumentEvent('Y', 'y-2', replacement_value, 'instrument/02:2')
            ))

        attempted = self.take('A', stale, before_take=collect_other)
        active = self.active()
        signed = receive(self.station, 'A')
        archived = self.archive_counts('A')
        self.assertEqual(
            (active, signed, archived), ({'X': x, 'Y': replacement[0]}, None, (0, 0, 0)),
            'GROUP_TAKE_MISMATCH: stale take changed active samples or signed an uncollected group',
        )
        self.assertEqual(attempted, CaptureStatus('A', 'invalid'))
        self.assertEqual((replacement[0].raw_value, replacement[0].generation, replacement[0].source),
                         (replacement_value, y.generation + 1, 'instrument/02:2'))
        binding = TakeBinding('A', self.main.version_id, stale.generations)
        self.assertEqual(device_outcome(self.device, binding).state, 'invalid')
        self.assertEqual(self.take('A', stale), attempted)
        self.assertEqual(shift(self.station, '甲班').group_count, 0)

    def test_overlap_changes_generation(self):
        self._check_overlap(11)

    def test_overlap_changed_value(self):
        self._check_overlap(31)

    def test_invalid_generation_vectors_leave_latches_and_order_absent(self):
        x, y = self.load_pair()
        for generations in ((('X', 1),), (('X', 1), ('X', 1)), (('Y', 1), ('Z', 1)),
                            (('Y', True), ('X', 1)), (('Y', 1), ('X', 0))):
            with self.subTest(generations=generations), self.assertRaises(ValueError):
                take_or_resume(self.station, self.device, '甲班', 'A', self.main.group_id, generations)
        with self.assertRaises(KeyError):
            load_order(self.station, 'A')
        self.assertEqual(self.active(), {'X': x, 'Y': y})
        archived = take_or_resume(self.station, self.device, '甲班', 'A', self.main.group_id,
                                   [('Y', 1), ('X', 1)])
        self.assertEqual([line.channel for line in archived.lines], ['X', 'Y'])
        self.assertEqual(self.take('A', self._original_preview(x, y)), archived)

    def _original_preview(self, x, y):
        from device.preview import GroupPreview
        return GroupPreview(self.main, (x, y))
