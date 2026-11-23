from contextlib import closing

from capture.order_store import CaptureOrder
from handover.archive import open_archive, read_capture_archive, write_capture_archive
from handover.lookup import SignedCapture, restore_signed_capture
from handover.receipt import issue_first_receipt
from quality.evaluation import QualityResult


def publish_capture(
    path, order: CaptureOrder, result: QualityResult, *, before_commit=None
) -> SignedCapture:
    request = order.request
    if order.state != 'verified' or order.group != result.group or result.group.binding != request.binding:
        raise ValueError('publication requires the verified group of this order')
    if tuple(line.measurement.original for line in result.lines) != result.group.readings:
        raise ValueError('publication requires complete quality details for the original group')

    with closing(open_archive(path)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            record = read_capture_archive(db, request.capture_id)
            if record is None:
                receipt = issue_first_receipt(request.capture_id)
                write_capture_archive(db, request, result, receipt)
                record = read_capture_archive(db, request.capture_id)
                if before_commit is not None:
                    before_commit(db)
            signed = restore_signed_capture(record)
            db.commit()
        except BaseException:
            db.rollback()
            raise
    return signed
