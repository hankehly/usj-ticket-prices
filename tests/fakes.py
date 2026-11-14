"""Test doubles for the store and the archive."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FakeStore:
    """Serves saved real responses and records every request made to it."""

    def __init__(self) -> None:
        self.requests: list[str] = []
        self.failing: set[str] = set()
        self.unreachable: set[str] = set()

    def product_list(self, category: str) -> bytes:
        return self._respond(f"product-list/{category}", fixture(f"product-list-{category}.json"))

    def sku_list(self, product_id: int) -> bytes:
        return self._respond(f"sku-list/{product_id}", fixture("sku-list-139.json"))

    def price_calendar(self, product_id: int) -> bytes:
        return self._respond(f"price-calendar/{product_id}", fixture("price-calendar-139.json"))

    def _respond(self, request: str, body: bytes) -> bytes:
        self.requests.append(request)
        if request in self.unreachable:
            raise TimeoutError("timed out")
        if request in self.failing:
            return fixture("error-parameter-error.json")
        return body


class InMemoryArchive:
    """Keeps responses in memory and, like the real archive, refuses to replace one."""

    def __init__(self) -> None:
        self.objects: dict[tuple[date, str], bytes] = {}
        self.fetched_at: dict[tuple[date, str], datetime] = {}
        self.manifests: dict[date, dict] = {}

    def stored_items(self, snapshot_date: date) -> set[str]:
        return {item for (stored_date, item) in self.objects if stored_date == snapshot_date}

    def read(self, snapshot_date: date, item: str) -> bytes:
        return self.objects[(snapshot_date, item)]

    def write(self, snapshot_date: date, item: str, body: bytes, fetched_at: datetime) -> None:
        if (snapshot_date, item) in self.objects:
            raise AssertionError(f"attempted to replace stored response {item}")
        self.objects[(snapshot_date, item)] = body
        self.fetched_at[(snapshot_date, item)] = fetched_at

    def write_manifest(self, snapshot_date: date, manifest: dict) -> None:
        self.manifests[snapshot_date] = manifest
