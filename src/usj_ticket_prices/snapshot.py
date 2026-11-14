"""Taking a Snapshot: one daily reading of the store's price calendars.

A Snapshot is write-once. Each response is stored exactly as the store returned
it, and a later run on the same date fetches only what is still missing.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Protocol

# Japan has no daylight saving time, so a fixed offset is exact.
JST = timezone(timedelta(hours=9), "JST")

# The store categories a Snapshot covers. See docs/adr/0001-snapshot-scope.md.
CATEGORIES = ("studio-pass", "express-pass")


class StoreError(Exception):
    """The store could not be reached or did not return usable data."""


class Store(Protocol):
    """The ticket store. Every method returns the response body as received."""

    def product_list(self, category: str) -> bytes: ...

    def sku_list(self, product_id: int) -> bytes: ...

    def price_calendar(self, product_id: int) -> bytes: ...


class Archive(Protocol):
    """Where a Snapshot's responses are kept, addressed by date and item name."""

    def stored_items(self, snapshot_date: date) -> set[str]: ...

    def read(self, snapshot_date: date, item: str) -> bytes: ...

    def write(
        self, snapshot_date: date, item: str, body: bytes, fetched_at: datetime
    ) -> None:
        """Store a response. Must never replace one that is already stored."""

    def write_manifest(self, snapshot_date: date, manifest: dict) -> None: ...


@dataclass(frozen=True)
class SnapshotResult:
    snapshot_date: date
    fetched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.missing


def snapshot_date(now: datetime) -> date:
    """The Japan-time calendar date a Snapshot taken at `now` belongs to."""
    return now.astimezone(JST).date()


def product_list_item(category: str) -> str:
    return f"product-list/{category}.json"


def sku_list_item(product_id: int) -> str:
    return f"sku-list/{product_id}.json"


def price_calendar_item(product_id: int) -> str:
    return f"price-calendar/{product_id}.json"


def check_response(body: bytes) -> dict:
    """Parse a store response, raising StoreError unless the store reports success.

    The store reports failures as HTTP 200 with `"status": 0`, so the HTTP
    status alone says nothing.
    """
    try:
        payload = json.loads(body)
    except ValueError as error:
        raise StoreError(f"response is not JSON: {error}") from error
    if not isinstance(payload, dict) or payload.get("status") != 1:
        message = payload.get("msg") if isinstance(payload, dict) else None
        raise StoreError(f"store reported failure: {message!r}")
    return payload


def product_ids(product_list_body: bytes) -> list[int]:
    return [int(product["id"]) for product in check_response(product_list_body)["data"]]


def take_snapshot(
    snapshot_date: date,
    store: Store,
    archive: Archive,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    failure_limit: int = 5,
) -> SnapshotResult:
    """Fetch and store whatever the Snapshot for `snapshot_date` still lacks.

    After `failure_limit` failures in a row the run stops asking the store, so
    an outage or a block is not met with dozens of further requests.
    """
    stored = archive.stored_items(snapshot_date)
    result = SnapshotResult(snapshot_date)
    failures_in_a_row = 0

    def ensure(item: str, fetch: Callable[[], bytes]) -> bool:
        nonlocal failures_in_a_row
        if item in stored:
            return True
        if failures_in_a_row >= failure_limit:
            result.missing.append(item)
            return False
        try:
            body = fetch()
            check_response(body)
        except (StoreError, OSError):
            failures_in_a_row += 1
            result.missing.append(item)
            return False
        failures_in_a_row = 0
        archive.write(snapshot_date, item, body, now())
        stored.add(item)
        result.fetched.append(item)
        return True

    # The product lists stored by the day's first run fix which products the
    # Snapshot covers, so later runs agree on what "missing" means.
    products: list[int] = []
    for category in CATEGORIES:
        item = product_list_item(category)
        if ensure(item, lambda: store.product_list(category)):
            for product_id in product_ids(archive.read(snapshot_date, item)):
                if product_id not in products:
                    products.append(product_id)

    for product_id in products:
        ensure(sku_list_item(product_id), lambda: store.sku_list(product_id))
        ensure(price_calendar_item(product_id), lambda: store.price_calendar(product_id))

    archive.write_manifest(
        snapshot_date,
        {
            "snapshot_date": snapshot_date.isoformat(),
            "complete": result.complete,
            "missing": result.missing,
            "checked_at": now().isoformat(),
        },
    )
    return result
