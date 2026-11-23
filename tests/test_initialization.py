from contextlib import closing
from pathlib import Path

from capture.intake import initialize_station
from capture.order_store import load_order
from capture.resume import CaptureStatus
from device.events import InstrumentEvent
from device.latch import latch
from device.store import open_device_store, read_device_channel
from profiles.channels import ChannelDefinition
from profiles.lookup import resolve_frozen_group
from profiles.store import load_channel_catalog
from profiles.versions import configure
from tests.support import StationCase, X_RULE, Y_RULE, lose_exchange


class InitializationTests(StationCase):
    def test_repeat_initialization_preserves_profile_and_catalog(self):
        x, y = self.load_pair()
        old = self.snapshot()
        self.assertEqual(self.take('wait', old, before_take=lose_exchange), CaptureStatus('wait', 'pending'))
        user_profile = configure(self.station, '卷纸机', '联检', [Y_RULE, X_RULE])
        initialize_station(self.station, self.device, [ChannelDefinition('Z', 'mV')])
        self.assertEqual(tuple(load_channel_catalog(self.station)), ('X', 'Y'))
        with closing(open_device_store(self.device)) as db:
            self.assertEqual(read_device_channel(db, 'Y').raw_unit, 'count')
            with self.assertRaises(ValueError):
                read_device_channel(db, 'Z')
        self.assertEqual(resolve_frozen_group(self.station, user_profile.group_id), user_profile)
        self.assertEqual(self.active(), {'X': x, 'Y': y})
        self.assertEqual(load_order(self.station, 'wait').state, 'pending')
        self.assertEqual(latch(self.device, InstrumentEvent('X', 'x-1', 7, 'instrument/01:1')), x)
        resumed = self.take('wait', old)
        self.assertEqual([line.channel for line in resumed.lines], ['X', 'Y'])
        self.assertEqual(resumed.receipt.number, 'R/wait')

    def test_station_and_device_cannot_share_a_file(self):
        unused = Path(self.root, 'unused.sqlite3')
        with self.assertRaises(ValueError):
            initialize_station(unused, unused, [ChannelDefinition('X', 'count')])
        self.assertFalse(unused.exists())
