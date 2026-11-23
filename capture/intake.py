from pathlib import Path
from typing import Iterable

from capture.joint import resolve_joint_ports, resume_joint
from capture.order_store import bind_joint_request, bind_request, initialize_order_store
from capture.requests import build_capture_request
from capture.resume import CaptureStatus, resume_capture
from device.preview import GroupPreview
from device.store import initialize_device_store
from handover.archive import initialize_archive
from handover.lookup import SignedCapture
from profiles.channels import ChannelDefinition
from profiles.lookup import resolve_frozen_group
from profiles.store import initialize_profile_store


def initialize_station(station_path, device_path, catalog: Iterable[ChannelDefinition]) -> None:
    station = Path(station_path).resolve()
    device = Path(device_path).resolve()
    if station == device or (station.exists() and device.exists() and station.samefile(device)):
        raise ValueError('the station and device require independent stores')
    registered = initialize_profile_store(station, catalog)
    initialize_device_store(device, registered)
    initialize_order_store(station)
    initialize_archive(station)


def take_or_resume(
    station_path,
    device_path,
    shift_id: str,
    capture_id: str,
    group_id: str,
    generations: Iterable[tuple[str, int]] | GroupPreview,
    *,
    before_take=None,
    after_take=None,
    before_publish_commit=None,
) -> SignedCapture | CaptureStatus:
    profile = resolve_frozen_group(station_path, group_id)
    request = build_capture_request(shift_id, capture_id, profile, generations)
    bind_request(station_path, request)
    return resume_capture(
        station_path, device_path, capture_id,
        before_take=before_take, after_take=after_take,
        before_publish_commit=before_publish_commit,
    )


def take_joint(
    station_path,
    ports,
    shift_id: str,
    capture_id: str,
    group_id: str,
    generations: Iterable[tuple[str, int]] | GroupPreview,
    *,
    before_publish_commit=None,
) -> SignedCapture | CaptureStatus:
    profile = resolve_frozen_group(station_path, group_id)
    request = build_capture_request(shift_id, capture_id, profile, generations)
    ports_by_channel = None if ports is None else resolve_joint_ports(profile, ports)
    order = bind_joint_request(station_path, request, ports_by_channel)
    if order is None:
        return CaptureStatus(capture_id, 'pending')
    return resume_joint(
        station_path, ports, capture_id, before_publish_commit=before_publish_commit
    )
