import json
from pathlib import Path
from tempfile import TemporaryDirectory

from capture.intake import initialize_station, take_or_resume
from capture.resume import CaptureStatus
from device.events import InstrumentEvent
from device.latch import latch
from device.preview import GroupPreview, preview
from handover.lookup import receive
from handover.shift_summary import shift
from profiles.channels import ChannelDefinition, ChannelRule
from profiles.versions import configure


def run_day(input_data, station, device):
    initialize_station(station, device, [ChannelDefinition(*item) for item in input_data['channels']])
    rules = [ChannelRule(*item) for item in input_data['rules']]
    main = configure(station, '卷纸机', '联检', rules)
    y_only = configure(station, '卷纸机', 'Y 复测', [rules[1]])

    for item in input_data['initial_events']:
        latch(device, InstrumentEvent(*item))
    initial = preview(station, device, main.group_id)
    assert isinstance(initial, GroupPreview)
    first = take_or_resume(station, device, '甲班', 'A-01', main.group_id, initial)
    values = [[row.channel, row.raw_value, row.converted_value, row.exceeded] for row in first.lines]
    expected = [['X', 7, 14, False], ['Y', 11, 22, True]]
    assert values == expected

    for item in input_data['overlap_events']:
        latch(device, InstrumentEvent(*item))
    stale = preview(station, device, main.group_id)
    spot = preview(station, device, y_only.group_id)
    reviewed = take_or_resume(station, device, '乙班', 'B-01', y_only.group_id, spot)
    assert [(row.raw_value, row.source) for row in reviewed.lines] == [(11, 'recorder/02:2')]
    latch(device, InstrumentEvent(*input_data['replacement_event']))
    attempt = take_or_resume(station, device, '甲班', 'A-stale', main.group_id, stale)
    current = preview(station, device, main.group_id)
    active = [[row.channel, row.generation, row.raw_value, row.source] for row in current.readings]
    expected_active = [['X', 2, 7, 'recorder/02:1'], ['Y', 3, 31, 'recorder/03:2']]
    assert active == expected_active
    assert attempt == CaptureStatus('A-stale', 'invalid')
    assert receive(station, 'A-stale') is None

    device.rename(device.with_name('offline.sqlite3'))
    assert receive(station, 'A-01') == first
    white = shift(station, '甲班')
    downstream = {'groups': white.group_count, 'exceedances': white.exceedances,
                  'receipt': first.receipt.number,
                  'sources': [[line.channel, line.source] for line in first.lines]}
    expected_downstream = {'groups': 1, 'exceedances': {'X': 0, 'Y': 1}, 'receipt': 'R/A-01',
                           'sources': [['X', 'recorder/01:1'], ['Y', 'recorder/01:2']]}
    assert downstream == expected_downstream
    assert white.sources == (('A-01', (('X', 'recorder/01:1'), ('Y', 'recorder/01:2'))),)
    assert shift(station, '乙班').group_count == 1
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': 'v4', 'input': {'events': input_data['initial_events'], 'rules': input_data['rules']},
        'expected': expected, 'actual': values,
        'downstream_expected': expected_downstream, 'downstream_actual': downstream,
        'code_paths': ['quality/conversion.py', 'quality/limits.py', 'quality/evaluation.py',
                       'handover/publish.py', 'handover/shift_summary.py'],
        'oracle': '手算 7×2=14 和 11×2=22，只有 22 大于 14。甲班只有 A-01 实际签发。',
    }, ensure_ascii=False, sort_keys=True))
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': 'v5.changed_value',
        'input': {'events': input_data['overlap_events'], 'new_y': input_data['replacement_event']},
        'expected': expected_active, 'actual': active,
        'downstream_expected': {'state': 'invalid', 'available': False},
        'downstream_actual': {'state': attempt.state, 'available': receive(station, 'A-stale') is not None},
        'code_paths': ['device/group_take.py', 'device/take_history.py', 'capture/settlement.py',
                       'handover/lookup.py'],
        'oracle': '乙班先取 Y 第二代。甲班引用的 Y 第二代已消失，故 X 第二代和 Y 第三代均须保留。',
    }, ensure_ascii=False, sort_keys=True))


def main():
    sample = Path(__file__).resolve().parent / 'examples' / 'day.json'
    with sample.open(encoding='utf-8') as stream:
        inputs = json.load(stream)
    with TemporaryDirectory(prefix='vibration-demo-') as directory:
        root = Path(directory)
        run_day(inputs, root / 'station.sqlite3', root / 'device.sqlite3')


if __name__ == '__main__':
    main()
