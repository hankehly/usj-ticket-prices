import io
from datetime import UTC, date, datetime

import pytest
from botocore.exceptions import ClientError
from botocore.response import StreamingBody

from tests.fakes import stubbed_s3
from usj_ticket_prices.archive import S3Archive

DAY = date(2026, 11, 15)
BUCKET = "snapshots-bucket"


def stubbed_archive():
    s3, stubber = stubbed_s3()
    return S3Archive(s3, BUCKET), stubber


def test_write_refuses_to_replace_a_stored_response():
    archive, stubber = stubbed_archive()
    stubber.add_response(
        "put_object",
        {},
        {
            "Bucket": BUCKET,
            "Key": "snapshots/2026-11-15/price-calendar/139.json",
            "Body": b'{"status":1}',
            "ContentType": "application/json",
            "Metadata": {"fetched-at": "2026-11-14T19:00:00+00:00"},
            "IfNoneMatch": "*",
        },
    )

    stored = archive.write(
        DAY, "price-calendar/139.json", b'{"status":1}', datetime(2026, 11, 14, 19, 0, tzinfo=UTC)
    )

    assert stored is True
    stubber.assert_no_pending_responses()


def test_write_reports_a_response_an_overlapping_run_stored_first():
    archive, stubber = stubbed_archive()
    stubber.add_client_error(
        "put_object", service_error_code="PreconditionFailed", http_status_code=412
    )

    stored = archive.write(DAY, "sku-list/139.json", b"{}", datetime(2026, 11, 14, tzinfo=UTC))

    assert stored is False


def test_write_does_not_hide_other_storage_errors():
    archive, stubber = stubbed_archive()
    stubber.add_client_error("put_object", service_error_code="AccessDenied", http_status_code=403)

    with pytest.raises(ClientError, match="AccessDenied"):
        archive.write(DAY, "sku-list/139.json", b"{}", datetime(2026, 11, 14, tzinfo=UTC))


def test_stored_items_lists_the_days_responses_but_not_the_manifest():
    archive, stubber = stubbed_archive()
    prefix = "snapshots/2026-11-15/"
    stubber.add_response(
        "list_objects_v2",
        {
            "IsTruncated": False,
            "Contents": [
                {"Key": prefix + "manifest.json"},
                {"Key": prefix + "product-list/studio-pass.json"},
                {"Key": prefix + "sku-list/139.json"},
            ],
        },
        {"Bucket": BUCKET, "Prefix": prefix},
    )

    assert archive.stored_items(DAY) == {"product-list/studio-pass.json", "sku-list/139.json"}


def test_stored_items_is_empty_before_the_first_run():
    archive, stubber = stubbed_archive()
    stubber.add_response(
        "list_objects_v2",
        {"IsTruncated": False, "KeyCount": 0},
        {"Bucket": BUCKET, "Prefix": "snapshots/2026-11-15/"},
    )

    assert archive.stored_items(DAY) == set()


def test_read_returns_the_stored_bytes():
    archive, stubber = stubbed_archive()
    stubber.add_response(
        "get_object",
        {"Body": StreamingBody(io.BytesIO(b'{"status":1}'), 12)},
        {"Bucket": BUCKET, "Key": "snapshots/2026-11-15/sku-list/139.json"},
    )

    assert archive.read(DAY, "sku-list/139.json") == b'{"status":1}'


def test_snapshot_dates_lists_every_date_with_stored_responses():
    archive, stubber = stubbed_archive()
    stubber.add_response(
        "list_objects_v2",
        {
            "IsTruncated": False,
            "CommonPrefixes": [
                {"Prefix": "snapshots/2026-11-16/"},
                {"Prefix": "snapshots/2026-11-15/"},
            ],
        },
        {"Bucket": BUCKET, "Prefix": "snapshots/", "Delimiter": "/"},
    )

    assert archive.snapshot_dates() == [date(2026, 11, 15), date(2026, 11, 16)]


def test_snapshot_dates_is_empty_before_the_first_snapshot():
    archive, stubber = stubbed_archive()
    stubber.add_response(
        "list_objects_v2",
        {"IsTruncated": False, "KeyCount": 0},
        {"Bucket": BUCKET, "Prefix": "snapshots/", "Delimiter": "/"},
    )

    assert archive.snapshot_dates() == []


def test_fetched_at_returns_the_time_stored_with_the_response():
    archive, stubber = stubbed_archive()
    stubber.add_response(
        "head_object",
        {"Metadata": {"fetched-at": "2026-11-14T19:00:07+00:00"}},
        {"Bucket": BUCKET, "Key": "snapshots/2026-11-15/price-calendar/139.json"},
    )

    assert archive.fetched_at(DAY, "price-calendar/139.json") == datetime(
        2026, 11, 14, 19, 0, 7, tzinfo=UTC
    )
