from datetime import UTC, date, datetime

import pytest

from tests.fakes import FakeStore, InMemoryArchive, fixture
from usj_ticket_prices.handler import run
from usj_ticket_prices.snapshot import (
    StoreError,
    check_response,
    product_ids,
    snapshot_date,
    take_snapshot,
)

DAY = date(2026, 11, 15)
STUDIO_PASS_IDS = product_ids(fixture("product-list-studio-pass.json"))
EXPRESS_PASS_IDS = product_ids(fixture("product-list-express-pass.json"))
ALL_IDS = STUDIO_PASS_IDS + EXPRESS_PASS_IDS


def test_first_run_of_the_day_stores_everything_the_store_lists():
    store, archive = FakeStore(), InMemoryArchive()

    result = take_snapshot(DAY, store, archive)

    expected = {"product-list/studio-pass.json", "product-list/express-pass.json"}
    for product_id in ALL_IDS:
        expected |= {f"sku-list/{product_id}.json", f"price-calendar/{product_id}.json"}
    assert archive.stored_items(DAY) == expected
    assert result.complete
    assert archive.manifests[DAY]["complete"] is True
    assert archive.manifests[DAY]["missing"] == []


def test_responses_are_stored_exactly_as_received_with_their_fetch_time():
    store, archive = FakeStore(), InMemoryArchive()
    fetched_at = datetime(2026, 11, 14, 19, 0, tzinfo=UTC)

    take_snapshot(DAY, store, archive, now=lambda: fetched_at)

    assert archive.read(DAY, "price-calendar/139.json") == fixture("price-calendar-139.json")
    assert archive.read(DAY, "product-list/studio-pass.json") == fixture(
        "product-list-studio-pass.json"
    )
    assert archive.fetched_at(DAY, "price-calendar/139.json") == fetched_at


def test_second_run_on_the_same_date_asks_the_store_for_nothing():
    store, archive = FakeStore(), InMemoryArchive()
    take_snapshot(DAY, store, archive)
    store.requests.clear()

    result = take_snapshot(DAY, store, archive)

    assert store.requests == []
    assert result.fetched == []
    assert result.complete


def test_a_failure_reported_by_the_store_is_not_stored():
    store, archive = FakeStore(), InMemoryArchive()
    store.failing = {"price-calendar/139"}

    result = take_snapshot(DAY, store, archive)

    assert result.missing == ["price-calendar/139.json"]
    assert not result.complete
    assert "price-calendar/139.json" not in archive.stored_items(DAY)
    assert archive.manifests[DAY]["complete"] is False
    assert archive.manifests[DAY]["missing"] == ["price-calendar/139.json"]


def test_an_unreachable_store_counts_as_a_failure():
    store, archive = FakeStore(), InMemoryArchive()
    store.unreachable = {"sku-list/145"}

    result = take_snapshot(DAY, store, archive)

    assert result.missing == ["sku-list/145.json"]


def test_a_later_run_fetches_only_what_is_missing_and_replaces_nothing():
    store, archive = FakeStore(), InMemoryArchive()
    store.failing = {"price-calendar/139", "sku-list/145"}
    take_snapshot(DAY, store, archive)
    stored_by_first_run = dict(archive.objects)
    store.failing = set()
    store.requests.clear()

    # InMemoryArchive raises if any stored response is written again.
    result = take_snapshot(DAY, store, archive)

    assert sorted(store.requests) == ["price-calendar/139", "sku-list/145"]
    assert result.complete
    for key, body in stored_by_first_run.items():
        assert archive.objects[key] == body


class OverlappedArchive(InMemoryArchive):
    """An archive in which another run stores one response just before this run does."""

    def __init__(self, contested_item: str) -> None:
        super().__init__()
        self.contested_item = contested_item

    def write(self, snapshot_date, item, body, fetched_at) -> bool:
        if item == self.contested_item:
            self.objects[(snapshot_date, item)] = body  # the other run's write
            return False
        return super().write(snapshot_date, item, body, fetched_at)


def test_a_response_stored_first_by_an_overlapping_run_does_not_stop_this_run():
    store, archive = FakeStore(), OverlappedArchive("product-list/studio-pass.json")

    result = take_snapshot(DAY, store, archive)

    assert result.complete
    assert "product-list/studio-pass.json" not in result.fetched
    assert "price-calendar/139.json" in archive.stored_items(DAY)
    assert archive.manifests[DAY]["complete"] is True


def test_a_failed_product_list_leaves_the_other_category_captured():
    store, archive = FakeStore(), InMemoryArchive()
    store.failing = {"product-list/express-pass"}

    result = take_snapshot(DAY, store, archive)

    assert result.missing == ["product-list/express-pass.json"]
    for product_id in STUDIO_PASS_IDS:
        assert f"price-calendar/{product_id}.json" in archive.stored_items(DAY)
    for product_id in EXPRESS_PASS_IDS:
        assert f"price-calendar/{product_id}.json" not in archive.stored_items(DAY)


def test_the_run_stops_asking_after_repeated_failures():
    store, archive = FakeStore(), InMemoryArchive()
    for product_id in ALL_IDS:
        store.failing |= {f"sku-list/{product_id}", f"price-calendar/{product_id}"}

    result = take_snapshot(DAY, store, archive, failure_limit=5)

    product_requests = [r for r in store.requests if not r.startswith("product-list/")]
    assert len(product_requests) == 5
    assert len(result.missing) == 2 * len(ALL_IDS)


def test_a_snapshot_belongs_to_the_japan_time_date():
    # 19:00 UTC on the 14th is 04:00 on the 15th in Japan.
    assert snapshot_date(datetime(2026, 11, 14, 19, 0, tzinfo=UTC)) == date(2026, 11, 15)
    assert snapshot_date(datetime(2026, 11, 14, 14, 59, tzinfo=UTC)) == date(2026, 11, 14)


def test_a_status_zero_response_is_a_failure_even_though_it_is_valid_json():
    with pytest.raises(StoreError, match="Parameter Error"):
        check_response(fixture("error-parameter-error.json"))
    with pytest.raises(StoreError):
        check_response(b"<html>home page</html>")


class Alerts:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def __call__(self, subject: str, message: str) -> None:
        self.sent.append((subject, message))


NOW = datetime(2026, 11, 15, 1, 0, tzinfo=UTC)  # 10:00 Japan time


def test_the_final_run_alerts_once_when_the_snapshot_is_incomplete():
    store, archive, alerts = FakeStore(), InMemoryArchive(), Alerts()
    store.failing = {"price-calendar/139"}

    run({"final": True}, store, archive, alerts, on_new_data=lambda: None, now=lambda: NOW)

    assert len(alerts.sent) == 1
    subject, message = alerts.sent[0]
    assert "2026-11-15" in subject
    assert "price-calendar/139.json" in message


def test_earlier_runs_do_not_alert_because_a_later_run_may_fill_the_gap():
    store, archive, alerts = FakeStore(), InMemoryArchive(), Alerts()
    store.failing = {"price-calendar/139"}

    run({"final": False}, store, archive, alerts, on_new_data=lambda: None, now=lambda: NOW)

    assert alerts.sent == []


def test_the_final_run_stays_quiet_when_the_snapshot_is_complete():
    store, archive, alerts = FakeStore(), InMemoryArchive(), Alerts()

    result = run({"final": True}, store, archive, alerts, on_new_data=lambda: None, now=lambda: NOW)

    assert alerts.sent == []
    assert result.snapshot_date == date(2026, 11, 15)


class Builds:
    def __init__(self) -> None:
        self.started = 0

    def __call__(self) -> None:
        self.started += 1


def test_a_run_that_added_data_starts_a_build_of_the_data_file():
    store, archive, builds = FakeStore(), InMemoryArchive(), Builds()

    run({"final": False}, store, archive, Alerts(), on_new_data=builds, now=lambda: NOW)

    assert builds.started == 1


def test_a_run_that_added_nothing_starts_no_build():
    store, archive, builds = FakeStore(), InMemoryArchive(), Builds()
    run({"final": False}, store, archive, Alerts(), on_new_data=lambda: None, now=lambda: NOW)

    run({"final": False}, store, archive, Alerts(), on_new_data=builds, now=lambda: NOW)

    assert builds.started == 0


def test_an_incomplete_final_run_that_added_data_both_alerts_and_starts_a_build():
    store, archive, alerts, builds = FakeStore(), InMemoryArchive(), Alerts(), Builds()
    store.failing = {"price-calendar/139"}

    run({"final": True}, store, archive, alerts, on_new_data=builds, now=lambda: NOW)

    assert len(alerts.sent) == 1
    assert builds.started == 1


def test_a_build_still_starts_when_the_alert_cannot_be_sent():
    store, archive, builds = FakeStore(), InMemoryArchive(), Builds()
    store.failing = {"price-calendar/139"}

    def broken_alert(subject: str, message: str) -> None:
        raise ConnectionError("alert service unreachable")

    with pytest.raises(ConnectionError):
        run({"final": True}, store, archive, broken_alert, on_new_data=builds, now=lambda: NOW)

    assert builds.started == 1


class FailingManifestArchive(InMemoryArchive):
    """An archive that stores responses but cannot write the manifest."""

    def write_manifest(self, snapshot_date, manifest) -> None:
        raise ConnectionError("storage unreachable")


def test_a_run_that_crashes_after_storing_data_still_starts_a_build():
    store, archive, builds = FakeStore(), FailingManifestArchive(), Builds()

    with pytest.raises(ConnectionError):
        run({"final": False}, store, archive, Alerts(), on_new_data=builds, now=lambda: NOW)

    assert "price-calendar/139.json" in archive.stored_items(date(2026, 11, 15))
    assert builds.started == 1


class ReadOnlyArchive(InMemoryArchive):
    """An archive that refuses every write."""

    def write(self, snapshot_date, item, body, fetched_at) -> bool:
        raise ConnectionError("storage unreachable")


def test_a_run_that_crashes_before_storing_anything_starts_no_build():
    store, archive, builds = FakeStore(), ReadOnlyArchive(), Builds()

    with pytest.raises(ConnectionError):
        run({"final": False}, store, archive, Alerts(), on_new_data=builds, now=lambda: NOW)

    assert builds.started == 0
