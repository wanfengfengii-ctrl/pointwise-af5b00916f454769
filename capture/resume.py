from dataclasses import dataclass
from typing import Literal

from capture.order_store import load_order
from capture.requests import CaptureRequest
from capture.settlement import settle_outcome
from device.group_take import DeviceExchangeInterrupted, take_group
from device.take_history import DeviceOutcome, device_outcome
from handover.lookup import SignedCapture, receive
from handover.publish import publish_capture
from profiles.lookup import load_frozen_profile
from quality.evaluation import evaluate_group


@dataclass(frozen=True, slots=True)
class CaptureStatus:
    capture_id: str
    state: Literal['pending', 'invalid']


def _contact_device(device_path, request: CaptureRequest, before_take, after_take) -> DeviceOutcome:
    binding = request.binding
    if device_path is None:
        return DeviceOutcome(binding, 'pending')
    try:
        outcome = device_outcome(device_path, binding)
        if outcome.state != 'pending':
            return outcome
        if before_take is not None:
            before_take(binding)
        outcome = take_group(device_path, binding)
        if after_take is not None:
            after_take(outcome)
        return outcome
    except DeviceExchangeInterrupted:
        return DeviceOutcome(binding, 'pending')


def resume_capture(
    station_path,
    device_path,
    capture_id: str,
    *,
    before_take=None,
    after_take=None,
    before_publish_commit=None,
) -> SignedCapture | CaptureStatus:
    order = load_order(station_path, capture_id)
    archived = receive(station_path, capture_id)
    if archived is not None:
        return archived
    if order.state == 'pending':
        outcome = _contact_device(device_path, order.request, before_take, after_take)
        order = settle_outcome(station_path, order.request, outcome)
    if order.state != 'verified':
        return CaptureStatus(capture_id, order.state)

    profile = load_frozen_profile(station_path, order.request.binding.version_id)
    if order.group is None:
        raise ValueError('verified order has no original group')
    result = evaluate_group(profile, order.group)
    return publish_capture(station_path, order, result, before_commit=before_publish_commit)
