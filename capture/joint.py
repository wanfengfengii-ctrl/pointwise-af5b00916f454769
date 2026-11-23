"""Station-side coordination of a two-recorder joint inspection."""
from capture.order_store import load_joint_order, mark_invalid, save_verified_group
from capture.requests import RequestConflict
from capture.resume import CaptureStatus
from device.group_take import DeviceExchangeInterrupted
from device.take_history import TakeBinding, TakenGroup
from handover.lookup import receive
from handover.publish import publish_capture
from profiles.channels import require_label
from profiles.lookup import load_frozen_profile
from quality.evaluation import evaluate_group


def resolve_joint_ports(profile, ports) -> dict:
    """Map every frozen group channel to the name of its serving port."""
    if not isinstance(ports, dict) or len(ports) != 2:
        raise ValueError('a joint inspection requires exactly two named ports')
    assignment = {}
    for name, port in ports.items():
        require_label(name, 'port name')
        channels = getattr(port, 'channels', None)
        if not isinstance(channels, tuple) or not channels:
            raise ValueError('each port must fix a nonempty channel tuple')
        if not callable(getattr(port, 'call', None)):
            raise ValueError('each port must forward recorder operations')
        for channel in channels:
            require_label(channel, 'port channel')
            if channel in assignment:
                raise ValueError(f'channel {channel!r} is served by more than one port')
            assignment[channel] = name
    missing = [channel for channel in profile.group.channels if channel not in assignment]
    if missing:
        raise ValueError(f'no port serves group channels {missing!r}')
    owners = {assignment[channel] for channel in profile.group.channels}
    if len(owners) != 2:
        raise ValueError('a joint inspection must select channels from both ports')
    return {channel: assignment[channel] for channel in profile.group.channels}


def _sub_bindings(binding: TakeBinding, ports_by_channel) -> dict:
    """Split the order binding into per-port vectors keeping the group order."""
    members = {}
    for pair in binding.generations:
        members.setdefault(ports_by_channel[pair[0]], []).append(pair)
    return {
        name: TakeBinding(binding.capture_id, binding.version_id, tuple(pairs))
        for name, pairs in members.items()
    }


def _check_outcome(sub: TakeBinding, outcome) -> None:
    if outcome.binding != sub:
        raise RequestConflict('recorder outcome does not match the joint binding')
    if outcome.state == 'taken':
        if outcome.group is None:
            raise ValueError('a taken joint outcome requires its group')
        outcome.group.require_complete()
    elif outcome.group is not None:
        raise ValueError('only a taken joint outcome carries a group')


def _drive_joint(station_path, ports, order, ports_by_channel):
    request = order.request
    binding = request.binding
    subs = _sub_bindings(binding, ports_by_channel)
    outcomes = {}
    for name, sub in subs.items():
        try:
            outcome = ports[name].call('prepare', sub)
        except DeviceExchangeInterrupted:
            return order
        _check_outcome(sub, outcome)
        outcomes[name] = outcome
    states = {name: outcome.state for name, outcome in outcomes.items()}
    if 'invalid' in states.values():
        return _settle_abort(station_path, ports, order, subs, outcomes)
    if all(state in ('prepared', 'taken') for state in states.values()):
        return _settle_take(station_path, ports, order, subs, outcomes, ports_by_channel)
    raise ValueError(f'unexpected recorder states {states!r}')


def _settle_abort(station_path, ports, order, subs, outcomes):
    settled = True
    for name, outcome in outcomes.items():
        if outcome.state == 'taken':
            raise ValueError('a taken recorder outcome cannot be revoked')
        if outcome.state != 'prepared':
            continue
        try:
            result = ports[name].call('abort', subs[name])
        except DeviceExchangeInterrupted:
            settled = False
            continue
        _check_outcome(subs[name], result)
        if result.state != 'aborted':
            settled = False
    if not settled:
        return order
    return mark_invalid(station_path, order.request)


def _settle_take(station_path, ports, order, subs, outcomes, ports_by_channel):
    taken = {}
    for name, sub in subs.items():
        outcome = outcomes[name]
        if outcome.state != 'taken':
            try:
                outcome = ports[name].call('commit', sub)
            except DeviceExchangeInterrupted:
                return order
            _check_outcome(sub, outcome)
        if outcome.state != 'taken':
            raise ValueError('joint commit did not reach a taken outcome')
        taken[name] = outcome
    binding = order.request.binding
    readings = []
    for channel, _ in binding.generations:
        group = taken[ports_by_channel[channel]].group
        readings.append(next(row for row in group.readings if row.channel == channel))
    group = TakenGroup(binding, tuple(readings))
    group.require_complete()
    return save_verified_group(station_path, order.request, group)


def resume_joint(
    station_path, ports, capture_id: str, *, before_publish_commit=None
):
    archived = receive(station_path, capture_id)
    if archived is not None:
        return archived
    order, ports_by_channel = load_joint_order(station_path, capture_id)
    if order.state == 'pending' and ports is not None:
        order = _drive_joint(station_path, ports, order, ports_by_channel)
    if order.state != 'verified':
        return CaptureStatus(capture_id, order.state)
    if order.group is None:
        raise ValueError('verified order has no original group')
    profile = load_frozen_profile(station_path, order.request.binding.version_id)
    result = evaluate_group(profile, order.group)
    return publish_capture(station_path, order, result, before_commit=before_publish_commit)
