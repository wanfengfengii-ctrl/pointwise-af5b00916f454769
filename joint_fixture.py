"""Set up two independent recorders and control delivery at their ports."""
import argparse
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable

import check_project
from capture.intake import take_or_resume
from capture.order_store import initialize_order_store
from capture.requests import RequestConflict
from capture.resume import CaptureStatus
from device.events import InstrumentEvent
from device.group_take import DeviceExchangeInterrupted, take_group
from device.latch import latch
from device.store import initialize_device_store
from device.take_history import TakeBinding, device_outcome
from handover.archive import initialize_archive
from handover.lookup import receive
from handover.shift_summary import shift
from profiles.channels import ChannelDefinition, ChannelRule
from profiles.store import initialize_profile_store
from profiles.versions import FrozenProfile, configure
from tests.support import reject_archive_commit

RECORDER_CHANNELS = {'A': ('X',), 'B': ('Y',)}


@dataclass(frozen=True)
class RecorderPort:
    channels: tuple[str, ...]
    exchange: Callable

    def call(self, operation, binding):
        return self.exchange(operation, binding)


@dataclass(frozen=True)
class Lab:
    station: Path
    devices: dict[str, Path]
    joint: FrozenProfile
    singles: dict[str, FrozenProfile]
    generations: tuple[tuple[str, int], ...]

    def ports(self, operations, *, before=None, after=None):
        def port(name, channels):
            def exchange(operation, binding):
                if before is not None:
                    before(name, operation, binding)
                outcome = operations[operation](self.devices[name], binding)
                if after is not None:
                    after(name, operation, binding, outcome)
                return outcome

            return RecorderPort(channels, exchange)

        return {name: port(name, channels) for name, channels in RECORDER_CHANNELS.items()}

    def ordinary(self, channel, generation, capture_id):
        name = next(name for name, channels in RECORDER_CHANNELS.items() if channel in channels)
        return take_or_resume(
            self.station, self.devices[name], '单测班', capture_id,
            self.singles[channel].group_id, ((channel, generation),),
        )

    def new_reading(self, name, raw_value):
        channel, = RECORDER_CHANNELS[name]
        return latch(self.devices[name], InstrumentEvent(channel, 'later', raw_value, f'{name}/later'))


def open_lab(root):
    with (Path(__file__).resolve().parent / 'examples' / 'day.json').open(encoding='utf-8') as stream:
        sample = json.load(stream)
    station = root / 'station.sqlite3'
    catalog = {item[0]: ChannelDefinition(*item) for item in sample['channels']}
    initialize_profile_store(station, catalog.values())
    initialize_order_store(station)
    initialize_archive(station)
    rules = [ChannelRule(*rule) for rule in sample['rules']]
    joint = configure(station, '卷纸机', '双仪联检', rules)
    singles = {rule.channel: configure(station, '卷纸机', rule.channel, [rule]) for rule in rules}
    devices = {name: root / f'{name}.sqlite3' for name in RECORDER_CHANNELS}
    initial = {item[0]: item for item in sample['initial_events']}
    readings = {}
    for name, channels in RECORDER_CHANNELS.items():
        initialize_device_store(devices[name], [catalog[channel] for channel in channels])
        for channel in channels:
            _, event_id, value, _ = initial[channel]
            event = InstrumentEvent(channel, event_id, value, f'{name}/initial')
            readings[channel] = latch(devices[name], event)
    generations = tuple((rule.channel, readings[rule.channel].generation) for rule in rules)
    return Lab(station, devices, joint, singles, generations)


def check_ports(root):
    lab = open_lab(root)
    binding = TakeBinding('port-smoke', lab.singles['X'].version_id, (('X', 1),))
    operations = {'take': take_group, 'status': device_outcome}

    def disconnected(name, operation, original):
        raise DeviceExchangeInterrupted('command not delivered')

    def lost_reply(name, operation, original, outcome):
        assert outcome.state == 'taken'
        raise DeviceExchangeInterrupted('reply lost after local commit')

    for hooks in ({'before': disconnected}, {'after': lost_reply}):
        try:
            lab.ports(operations, **hooks)['A'].call('take', binding)
        except DeviceExchangeInterrupted:
            status_port = lab.ports(operations)['A']
            outcome = status_port.call('status', binding)
            assert outcome.state == ('pending' if 'before' in hooks else 'taken')
        else:
            raise AssertionError('the port did not interrupt the exchange')
    assert [(row.raw_value, row.source) for row in outcome.group.readings] == [(7, 'A/initial')]
    second = lab.ordinary('Y', 1, 'independent-Y')
    assert [(row.raw_value, row.source) for row in second.lines] == [(11, 'B/initial')]
    print('双端口夹具：A 失答后认回 7，B 普通取读 11')


def submit(lab, ports, **hooks):
    from capture.intake import take_joint

    return take_joint(
        lab.station, ports, '联检班', 'J1', lab.joint.group_id,
        tuple(reversed(lab.generations)), **hooks,
    )


def port_operations():
    from device.joint_take import abort, commit, prepare, status

    return {'prepare': prepare, 'commit': commit, 'abort': abort, 'status': status}


def check_no_publication(lab):
    assert receive(lab.station, 'J1') is None
    assert shift(lab.station, '联检班').group_count == 0


def check_abort(root, *, consume_new_generation):
    lab = open_lab(root)
    original = {'X': 7, 'Y': 11}
    interleaving = []

    def after(name, operation, binding, outcome):
        if operation != 'prepare' or outcome.state != 'prepared' or interleaving:
            return
        other = 'B' if name == 'A' else 'A'
        channel, = RECORDER_CHANNELS[name]
        other_channel, = RECORDER_CHANNELS[other]
        interleaving.append((channel, other_channel))
        assert lab.ordinary(channel, 1, 'held') == CaptureStatus('held', 'pending')
        if consume_new_generation:
            new = lab.new_reading(name, original[channel])
            signed = lab.ordinary(channel, new.generation, 'new-on-held-side')
            assert (signed.lines[0].generation, signed.lines[0].source) == (2, f'{name}/later')
        lab.new_reading(other, 31)

    assert submit(lab, lab.ports(port_operations(), after=after)) == CaptureStatus('J1', 'invalid')
    assert interleaving, 'the recorder never reported a temporary hold'
    channel, other_channel = interleaving[0]
    original_take = lab.ordinary(channel, 1, 'held')
    if consume_new_generation:
        assert original_take == CaptureStatus('held', 'invalid')
    else:
        assert (original_take.lines[0].raw_value, original_take.lines[0].generation) == (original[channel], 1)
    replacement = lab.ordinary(other_channel, 2, 'replacement')
    assert (replacement.lines[0].raw_value, replacement.lines[0].generation) == (31, 2)
    assert submit(lab, None) == CaptureStatus('J1', 'invalid')
    check_no_publication(lab)


def check_resumed_take(root):
    lab = open_lab(root)
    operations = port_operations()
    interrupted = set()

    def before(name, operation, binding):
        if name in interrupted:
            raise DeviceExchangeInterrupted('recorder temporarily unreachable')

    def after(name, operation, binding, outcome):
        if operation == 'commit' and outcome.state == 'taken' and not interrupted:
            interrupted.add(name)
            raise DeviceExchangeInterrupted('reply lost after actual take')

    assert submit(lab, lab.ports(operations, before=before, after=after)) == CaptureStatus('J1', 'pending')
    assert interrupted, 'the loss must follow an actual take'
    check_no_publication(lab)
    replacement = lab.new_reading('B', 31)
    try:
        submit(lab, lab.ports(operations), before_publish_commit=reject_archive_commit)
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError('publication failed to expose its commit error')
    check_no_publication(lab)
    new_take = lab.ordinary('Y', replacement.generation, 'later-Y')
    assert [(row.generation, row.raw_value) for row in new_take.lines] == [(2, 31)]
    for path in lab.devices.values():
        path.rename(path.with_suffix('.offline'))
    signed = submit(lab, None)
    assert receive(lab.station, 'J1') == submit(lab, None) == signed
    actual = [(row.channel, row.raw_value, row.converted_value, row.exceeded, row.generation,
               row.event_id, row.source) for row in signed.lines]
    assert actual == [('X', 7, 14, False, 1, 'x-1', 'A/initial'),
                      ('Y', 11, 22, True, 1, 'y-1', 'B/initial')]
    assert signed.receipt.number == 'R/J1'
    summary = shift(lab.station, '联检班')
    assert summary.group_count == 1
    assert summary.exceedances == {'X': 0, 'Y': 1}
    assert summary.sources == (('J1', (('X', 'A/initial'), ('Y', 'B/initial'))),)
    try:
        take_or_resume(lab.station, None, '联检班', 'J1', lab.joint.group_id, lab.generations)
    except RequestConflict:
        pass
    else:
        raise AssertionError('the ordinary entry accepted a joint capture ID')
    return {'capture': signed.capture_id, 'receipt': signed.receipt.number,
            'lines': actual, 'groups': summary.group_count, 'exceedances': summary.exceedances}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', nargs='?', choices=('smoke', 'verify', 'demo'), default='smoke')
    args = parser.parse_args()
    if args.mode == 'smoke':
        with TemporaryDirectory(prefix='joint-ports-') as directory:
            check_ports(Path(directory))
        return 0
    if args.mode == 'verify':
        prior = check_project.main()
        if prior:
            return prior
        for consume_new in (False, True):
            with TemporaryDirectory(prefix='joint-abort-') as path:
                check_abort(Path(path), consume_new_generation=consume_new)
    with TemporaryDirectory(prefix='joint-take-') as path:
        actual = check_resumed_take(Path(path))
    print('停源领取 ' + json.dumps(actual, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
