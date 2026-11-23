from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FirstReceipt:
    capture_id: str
    number: str


def issue_first_receipt(capture_id: str) -> FirstReceipt:
    return FirstReceipt(capture_id, f'R/{capture_id}')
