import sqlite3

from capture.intake import take_or_resume
from capture.order_store import load_order
from capture.requests import RequestConflict
from capture.resume import CaptureStatus
from device.events import InstrumentEvent
from device.latch import latch
from device.take_history import TakeBinding, device_outcome
from handover.lookup import receive
from handover.shift_summary import shift
from profiles.versions import configure
from tests.support import StationCase, X_RULE, Y_RULE, lose_exchange, reject_archive_commit


class RecoveryTests(StationCase):
    def _start_lost_reply(self):
        self.load_pair()
        old = self.snapshot()
        state = self.take('A', old, after_take=lose_exchange)
        self.assertEqual(state, CaptureStatus('A', 'pending'))
        self.assertEqual(self.active(), {})
        self.assertIsNone(receive(self.station, 'A'))
        self.assertEqual(self.archive_counts('A'), (0, 0, 0))
        return old

    def test_taken_reply_lost(self):
        old = self._start_lost_reply()
        later = latch(self.device, InstrumentEvent('Y', 'y-2', 31, 'instrument/02:2'))
        signed = self.take('A', old)
        self.assertEqual([(row.raw_value, row.source) for row in signed.lines],
                         [(7, 'instrument/01:1'), (11, 'instrument/01:2')])
        self.assertEqual(signed, receive(self.station, 'A'))
        self.assertEqual(self.archive_counts('A'), (1, 2, 1))
        self.assertEqual(self.active(), {'Y': later})
        self.assertEqual(self.take('A', old, offline=True).receipt, signed.receipt)

    def test_before_clear_unconfirmed(self):
        x, y = self.load_pair()
        old = self.snapshot()
        binding = TakeBinding('A', self.main.version_id, old.generations)
        self.assertEqual(self.take('A', old, before_take=lose_exchange), CaptureStatus('A', 'pending'))
        self.assertEqual(device_outcome(self.device, binding).state, 'pending')
        self.assertEqual(load_order(self.station, 'A').state, 'pending')
        self.assertEqual(self.active(), {'X': x, 'Y': y})
        self.assertIsNone(receive(self.station, 'A'))
        self.assertEqual(self.archive_counts('A'), (0, 0, 0))
        self.assertEqual(self.take('B', self.snapshot(self.y_only), '乙班').lines[0].raw_value, 11)
        new_y = latch(self.device, InstrumentEvent('Y', 'y-2', 31, 'instrument/02:2'))
        self.assertEqual(self.take('A', old), CaptureStatus('A', 'invalid'))
        self.assertEqual(self.active(), {'X': x, 'Y': new_y})
        self.assertEqual(self.archive_counts('A'), (0, 0, 0))

    def test_original_outcome(self):
        old = self._start_lost_reply()
        current = latch(self.device, InstrumentEvent('Y', 'y-2', 31, 'instrument/02:2'))
        binding = TakeBinding('A', self.main.version_id, old.generations)
        outcome = device_outcome(self.device, binding)
        self.assertEqual(outcome.state, 'taken')
        self.assertEqual(outcome.binding, binding)
        self.assertEqual([(row.channel, row.generation, row.raw_value, row.source)
                          for row in outcome.group.readings],
                         [('X', 1, 7, 'instrument/01:1'), ('Y', 1, 11, 'instrument/01:2')])
        with self.assertRaises(ValueError):
            device_outcome(self.device, TakeBinding('A', self.main.version_id, (('X', 1), ('Y', 2))))
        signed = self.take('A', old)
        self.assertEqual([row.event_id for row in signed.lines], ['x-1', 'y-1'])
        self.assertEqual(self.active(), {'Y': current})

    def test_same_value_after_clear(self):
        old = self._start_lost_reply()
        later = latch(self.device, InstrumentEvent('Y', 'y-2', 11, 'instrument/02:2'))
        first = self.take('A', old)
        self.assertEqual(self.active(), {'Y': later})
        second = self.take('B', self.snapshot(self.y_only))
        self.assertEqual([(read.generation, read.raw_value, read.source) for read in
                          (first.lines[1], second.lines[0])],
                         [(1, 11, 'instrument/01:2'), (2, 11, 'instrument/02:2')])
        self.assertNotEqual(first.receipt, second.receipt)
        self.assertEqual(self.active(), {})

    def _fail_publication(self):
        self.load_pair()
        original = self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):
            self.take('A', original, before_publish_commit=reject_archive_commit)
        return original

    def test_publish_retry(self):
        old = self._fail_publication()
        self.assertEqual(self.active(), {})
        self.assertIsNone(receive(self.station, 'A'))
        self.assertEqual(shift(self.station, '甲班').group_count, 0)
        self.device.rename(self.root / 'offline.sqlite3')
        signed = self.take('A', old, offline=True)
        self.assertEqual(signed.receipt.number, 'R/A')
        self.assertEqual(self.take('A', old, offline=True), signed)
        self.assertEqual(self.archive_counts('A'), (1, 2, 1))
        self.assertEqual(shift(self.station, '甲班').group_count, 1)

    def test_no_partial_archive(self):
        self.load_pair()
        old = self.snapshot()
        observations = []

        def fail_commit(db):
            observations.append((self.archive_counts('A'), receive(self.station, 'A')))
            reject_archive_commit(db)

        with self.assertRaises(sqlite3.IntegrityError):
            self.take('A', old, before_publish_commit=fail_commit)
        self.assertEqual(observations, [((0, 0, 0), None)])
        self.assertEqual(self.archive_counts('A'), (0, 0, 0))
        self.assertEqual(load_order(self.station, 'A').state, 'verified')
        self.assertEqual(self.take('A', old, offline=True), receive(self.station, 'A'))
        self.assertEqual(self.archive_counts('A'), (1, 2, 1))

    def test_changed_binding(self):
        self.load_pair()
        old = self.snapshot()
        signed = self.take('A', old)
        self.assertEqual(self.take('A', old), signed)
        updated = configure(self.station, '卷纸机', '联检', [X_RULE, Y_RULE])
        for shift_id, group_id, generations in (
            ('乙班', self.main.group_id, old.generations),
            ('甲班', updated.group_id, old.generations),
            ('甲班', self.main.group_id, (('X', 1), ('Y', 2))),
        ):
            with self.subTest(shift=shift_id, group=group_id, generations=generations):
                with self.assertRaises(RequestConflict):
                    take_or_resume(self.station, self.device, shift_id, 'A', group_id, generations)
        self.assertEqual(receive(self.station, 'A'), signed)
        self.assertEqual(self.archive_counts('A'), (1, 2, 1))
        self.assertEqual(self.active(), {})

    def test_later_capture(self):
        old = self._fail_publication()
        latch(self.device, InstrumentEvent('Y', 'y-2', 31, 'instrument/02:2'))
        later = self.take('B', self.snapshot(self.y_only), '乙班')
        self.assertIsNone(receive(self.station, 'A'))
        self.assertEqual(self.archive_counts('A'), (0, 0, 0))
        first = self.take('A', old, offline=True)
        self.assertEqual([(line.raw_value, line.source) for line in first.lines],
                         [(7, 'instrument/01:1'), (11, 'instrument/01:2')])
        self.assertEqual([(line.raw_value, line.source) for line in later.lines], [(31, 'instrument/02:2')])
        self.assertEqual([first.receipt.number, later.receipt.number], ['R/A', 'R/B'])
        self.assertEqual([shift(self.station, name).group_count for name in ('甲班', '乙班')], [1, 1])
