from capture.order_store import CaptureOrder, load_order, mark_invalid, save_verified_group
from capture.requests import CaptureRequest, RequestConflict, require_same_request
from device.take_history import DeviceOutcome


def settle_outcome(path, request: CaptureRequest, outcome: DeviceOutcome) -> CaptureOrder:
    if outcome.binding != request.binding:
        raise RequestConflict('device outcome does not match the original request')
    if outcome.state == 'taken':
        if outcome.group is None:
            raise ValueError('taken outcome is missing the actual original group')
        return save_verified_group(path, request, outcome.group)
    if outcome.group is not None:
        raise ValueError('only a confirmed take can carry an actual group')
    if outcome.state == 'invalid':
        return mark_invalid(path, request)
    if outcome.state == 'pending':
        order = load_order(path, request.capture_id)
        require_same_request(order.request, request)
        return order
    raise ValueError(f'unknown device outcome {outcome.state!r}')
