from device.events import InstrumentEvent
from device.latch import latch
from device.preview import PreviewPending, preview
from profiles.channels import ChannelRule
from profiles.lookup import load_frozen_profile, resolve_frozen_group
from profiles.versions import configure
from tests.support import StationCase, X_RULE, Y_RULE


class ProfileTests(StationCase):
    def test_group_preview(self):
        self.load_pair()
        snapshot = self.snapshot()
        self.assertEqual(snapshot.profile, self.main)
        self.assertEqual(snapshot.generations, (('X', 1), ('Y', 1)))
        self.assertEqual(
            [(reading.raw_value, reading.raw_unit, reading.event_id, reading.source)
             for reading in snapshot.readings],
            [(7, 'count', 'x-1', 'instrument/01:1'), (11, 'count', 'y-1', 'instrument/01:2')],
        )

    def test_profile_rejections(self):
        cases = (
            (), (X_RULE, X_RULE), (ChannelRule('Z', 'count', 'μm/s', 2, 14),),
            (ChannelRule('X', 'mV', 'μm/s', 2, 14),), (ChannelRule('X', 'count', ' ', 2, 14),),
            (ChannelRule('X', 'count', 'μm/s', 0, 14),), (ChannelRule('X', 'count', 'μm/s', True, 14),),
            (ChannelRule('X', 'count', 'μm/s', 2, 14.0),),
            (ChannelRule('X', 'count', 'μm/s', 2, None),),
        )
        for rules in cases:
            with self.subTest(rules=rules), self.assertRaises(ValueError):
                configure(self.station, '卷纸机', '联检', rules)
        self.assertEqual(resolve_frozen_group(self.station, self.main.group_id), self.main)
        next_version = configure(self.station, '卷纸机', '联检', (X_RULE, Y_RULE))
        self.assertEqual(next_version.revision, 2)
        with self.assertRaises(KeyError):
            preview(self.station, self.device, 'missing-group')

    def test_version_freeze(self):
        self.load_pair()
        original = self.snapshot()
        newer = configure(self.station, '卷纸机', '联检', (
            ChannelRule('Y', 'count', 'μm/s', 5, 70), X_RULE,
        ))
        self.assertNotEqual(newer.group_id, self.main.group_id)
        self.assertEqual(newer.revision, 2)
        self.assertEqual(self.snapshot(), original)
        self.assertEqual(load_frozen_profile(self.station, self.main.version_id), self.main)
        changed = self.snapshot(newer)
        self.assertEqual(changed.profile.group.rules[0].multiplier, 5)
        self.assertEqual(changed.profile.group.rules[0].threshold, 70)
        self.assertEqual(changed.generations, (('Y', 1), ('X', 1)))
        self.assertEqual([row.source for row in changed.readings], ['instrument/01:2', 'instrument/01:1'])


class LatchTests(StationCase):
    def test_invalid_and_duplicate_input(self):
        event = InstrumentEvent('X', 'x-1', 7, 'instrument/01:1')
        accepted = latch(self.device, event)
        self.assertEqual(latch(self.device, event), accepted)
        for index, value in enumerate((False, 7.0, '7', None)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                latch(self.device, InstrumentEvent('X', f'invalid-{index}', value, 'instrument/02:1'))
        with self.assertRaises(ValueError):
            latch(self.device, InstrumentEvent('X', 'bad-source', 9, ' '))
        with self.assertRaises(ValueError):
            latch(self.device, InstrumentEvent('Z', 'z-1', 9, 'instrument/02:1'))
        self.assertEqual(self.active(), {'X': accepted})
        fresh = latch(self.device, InstrumentEvent('X', 'x-2', 9, 'instrument/02:2'))
        self.assertEqual(fresh.generation, 2)

    def test_old_event_replay(self):
        old, y = self.load_pair()
        current = latch(self.device, InstrumentEvent('X', 'x-2', 7, 'instrument/02:1'))
        self.assertEqual(latch(self.device, InstrumentEvent('X', 'x-1', 7, 'instrument/01:1')), old)
        self.assertEqual(self.snapshot().readings, (current, y))
        signed = self.take('X-replay', self.snapshot())
        self.assertEqual(signed.lines[0].source, 'instrument/02:1')
        self.assertEqual(latch(self.device, InstrumentEvent('X', 'x-2', 7, 'instrument/02:1')), current)
        self.assertEqual(self.active(), {})

    def test_conflicting_replay(self):
        original, y = self.load_pair()
        for event in (
            InstrumentEvent('X', 'x-1', 8, original.source),
            InstrumentEvent('X', 'x-1', 7, 'instrument/wrong:1'),
        ):
            with self.subTest(event=event), self.assertRaises(ValueError):
                latch(self.device, event)
        self.assertEqual(self.snapshot().readings, (original, y))

    def test_missing_channel(self):
        x = latch(self.device, InstrumentEvent('X', 'x-1', 7, 'instrument/01:1'))
        self.assertEqual(preview(self.station, self.device, self.main.group_id), PreviewPending(self.main, ('Y',)))
        self.assertEqual(self.active(), {'X': x})
        y = latch(self.device, InstrumentEvent('Y', 'y-1', 11, 'instrument/01:2'))
        self.assertEqual(self.snapshot().readings, (x, y))
