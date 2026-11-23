from dataclasses import dataclass
from typing import Iterable

from device.preview import GroupPreview
from device.take_history import TakeBinding
from profiles.channels import require_label
from profiles.versions import FrozenProfile


class RequestConflict(ValueError):
    """An existing capture ID is bound to another request."""


@dataclass(frozen=True, slots=True)
class CaptureRequest:
    shift_id: str
    binding: TakeBinding

    def __post_init__(self) -> None:
        require_label(self.shift_id, 'shift ID')

    @property
    def capture_id(self) -> str:
        return self.binding.capture_id


def build_capture_request(
    shift_id: str,
    capture_id: str,
    profile: FrozenProfile,
    generations: Iterable[tuple[str, int]] | GroupPreview,
) -> CaptureRequest:
    if isinstance(generations, GroupPreview):
        if generations.profile != profile:
            raise ValueError('preview refers to a different frozen profile')
        generations = generations.generations
    supplied = {}
    for pair in generations:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError('expected a channel and generation pair')
        channel, generation = pair
        require_label(channel, 'bound channel')
        if channel in supplied:
            raise ValueError(f'duplicate bound channel {channel!r}')
        supplied[channel] = generation
    channels = profile.group.channels
    if supplied.keys() != set(channels):
        raise ValueError('request must name every channel in the frozen group exactly once')
    ordered = tuple((channel, supplied[channel]) for channel in channels)
    return CaptureRequest(shift_id, TakeBinding(capture_id, profile.version_id, ordered))


def require_same_request(original: CaptureRequest, incoming: CaptureRequest) -> None:
    if original != incoming:
        raise RequestConflict(f'capture ID {incoming.capture_id!r} already has a different binding')
