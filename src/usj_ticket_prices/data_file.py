"""The data file: everything the public page shows, calculated ahead of time.

It is built from the stored Snapshots alone, so building it again over the
same Snapshots gives the same file, byte for byte.

Only a price that could be bought counts towards the Opening Price, the Final
Price and the change by Lead Time. The store's price for an Unavailable Visit
Date is passed on with its state but never enters those figures.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from itertools import pairwise
from typing import Protocol

from usj_ticket_prices.observations import CalendarReading, PriceObservation, read_price_calendar
from usj_ticket_prices.snapshot import price_calendar_item, sku_list_item

# The one price series the page charts: the 1 Day Studio Pass for an Adult.
PRODUCT_ID = 139
GUEST_TYPE = "Adult"

# The shortest Lead Time charted. A Visit Date on the Snapshot's own date has
# a Lead Time of zero and is left out.
SHORTEST_LEAD_TIME = 1


class State(StrEnum):
    """What one Snapshot showed for a Visit Date."""

    AVAILABLE = "available"
    # In the calendar, but marked not purchasable or without a price for the
    # Guest Type.
    UNAVAILABLE = "unavailable"
    # Missing from the calendar.
    NOT_LISTED = "not_listed"
    # The store's data does not settle which SKU prices the Guest Type, and
    # none is picked.
    SKU_CONFLICT = "sku_conflict"


class SnapshotHistory(Protocol):
    """Every stored Snapshot, read-only."""

    def snapshot_dates(self) -> list[date]: ...

    def stored_items(self, snapshot_date: date) -> set[str]: ...

    def read(self, snapshot_date: date, item: str) -> bytes: ...

    def fetched_at(self, snapshot_date: date, item: str) -> datetime: ...


@dataclass(frozen=True)
class _Sighting:
    """What one Snapshot showed for one Visit Date of the price series."""

    snapshot_date: date
    state: State
    price: int | None = None
    sku_id: int | None = None

    @property
    def bought_price(self) -> int | None:
        """The price, if it is one a guest could have paid."""
        return self.price if self.state == State.AVAILABLE else None


# Each Visit Date ever observed, with its sighting in every Snapshot whose
# calendar reached it, oldest Snapshot first.
_Series = dict[date, list[_Sighting]]


def build_data_file(history: SnapshotHistory) -> bytes:
    readings = _readings(history)
    spans = _spans(readings)
    series, sku_conflicts = _series(readings, spans)
    latest = readings[-1] if readings else None

    data = {
        "product": {"id": PRODUCT_ID, "title": latest.product_title if latest else None},
        "guest_type": GUEST_TYPE,
        "latest_snapshot": _latest_snapshot(history, latest),
        "upcoming_prices": _upcoming_prices(series, latest, spans),
        "final_prices": _final_prices(series),
        "change_by_lead_time": _change_by_lead_time(series, readings),
        "histories": {
            visit_date.isoformat(): [
                {
                    "snapshot_date": sighting.snapshot_date.isoformat(),
                    "state": sighting.state,
                    "price": sighting.price,
                    "sku_id": sighting.sku_id,
                }
                for sighting in sightings
            ]
            for visit_date, sightings in series.items()
        },
        "flags": {"sku_changes": _sku_changes(series), "sku_conflicts": sku_conflicts},
    }
    return json.dumps(data, separators=(",", ":")).encode()


def _readings(history: SnapshotHistory) -> list[CalendarReading]:
    """The product's price calendar in every Snapshot that has it, oldest first."""
    sku_list, price_calendar = sku_list_item(PRODUCT_ID), price_calendar_item(PRODUCT_ID)
    return [
        read_price_calendar(
            snapshot_date,
            PRODUCT_ID,
            history.read(snapshot_date, sku_list),
            history.read(snapshot_date, price_calendar),
        )
        for snapshot_date in sorted(history.snapshot_dates())
        if {sku_list, price_calendar} <= history.stored_items(snapshot_date)
    ]


def _series(
    readings: list[CalendarReading], spans: dict[date, list[date]]
) -> tuple[_Series, list[dict]]:
    """The price series, and every SKU conflict met while reading it."""
    series: _Series = defaultdict(list)
    sku_conflicts = []
    for reading in readings:
        candidates: dict[date, list[PriceObservation]] = defaultdict(list)
        for observation in reading.observations:
            if GUEST_TYPE in observation.guest_types:
                candidates[observation.visit_date].append(observation)

        listed = set(reading.visit_dates)
        for visit_date in spans[reading.snapshot_date]:
            observations = sorted(candidates[visit_date], key=lambda each: each.sku_id)
            if visit_date not in listed:
                sighting = _Sighting(reading.snapshot_date, State.NOT_LISTED)
            elif not observations:
                sighting = _Sighting(reading.snapshot_date, State.UNAVAILABLE)
            elif len(observations) > 1 or observations[0].guest_types != {GUEST_TYPE}:
                sighting = _Sighting(reading.snapshot_date, State.SKU_CONFLICT)
                sku_conflicts.append(
                    {
                        "snapshot_date": reading.snapshot_date.isoformat(),
                        "visit_date": visit_date.isoformat(),
                        "skus": [
                            {
                                "sku_id": observation.sku_id,
                                "price": observation.price,
                                "guest_types": sorted(observation.guest_types),
                            }
                            for observation in observations
                        ],
                    }
                )
            else:
                (observation,) = observations
                sighting = _Sighting(
                    reading.snapshot_date,
                    State.AVAILABLE if observation.purchasable else State.UNAVAILABLE,
                    observation.price,
                    observation.sku_id,
                )
            series[visit_date].append(sighting)

    ever_observed = {
        visit_date: series[visit_date]
        for visit_date in sorted(series)
        if any(sighting.state != State.NOT_LISTED for sighting in series[visit_date])
    }
    return ever_observed, sku_conflicts


def _spans(readings: list[CalendarReading]) -> dict[date, list[date]]:
    """For each Snapshot date, every date its calendar is held to account
    for: from the Snapshot's date to the latest Visit Date listed so far, in
    this Snapshot or any earlier one. The ones it leaves out are Not Listed.

    Reaching back to earlier Snapshots matters when a calendar shrinks or
    comes back empty: the Visit Dates it dropped are Not Listed, not unknown.
    """
    spans = {}
    latest_listed = None
    for reading in readings:
        first = reading.snapshot_date
        if reading.visit_dates:
            first = min(first, reading.visit_dates[0])
            last = reading.visit_dates[-1]
            latest_listed = last if latest_listed is None else max(latest_listed, last)
        days = (latest_listed - first).days + 1 if latest_listed else 0
        spans[reading.snapshot_date] = [first + timedelta(days=offset) for offset in range(days)]
    return spans


def _latest_snapshot(history: SnapshotHistory, latest: CalendarReading | None) -> dict | None:
    if latest is None:
        return None
    taken_at = history.fetched_at(latest.snapshot_date, price_calendar_item(PRODUCT_ID))
    return {
        "date": latest.snapshot_date.isoformat(),
        "taken_at": taken_at.astimezone(UTC).isoformat(),
    }


def _upcoming_prices(
    series: _Series, latest: CalendarReading | None, spans: dict[date, list[date]]
) -> list[dict]:
    if latest is None:
        return []
    upcoming = []
    for visit_date in spans[latest.snapshot_date]:
        # A date missing from the series has never been listed in any Snapshot.
        sighting = _Sighting(latest.snapshot_date, State.NOT_LISTED)
        if visit_date in series and series[visit_date][-1].snapshot_date == latest.snapshot_date:
            sighting = series[visit_date][-1]
        upcoming.append(
            {
                "visit_date": visit_date.isoformat(),
                "state": sighting.state,
                "price": sighting.price,
            }
        )
    return upcoming


def _final_prices(series: _Series) -> list[dict]:
    """The Final Price of each Visit Date. While a Visit Date is still in the
    calendar this is its latest price, which a later Snapshot may replace."""
    final_prices = []
    for visit_date, sightings in series.items():
        bought_prices = [
            sighting.bought_price for sighting in sightings if sighting.bought_price is not None
        ]
        if bought_prices:
            final_prices.append(
                {
                    "visit_date": visit_date.isoformat(),
                    "weekday": visit_date.isoweekday(),  # Monday is 1, Sunday is 7.
                    "price": bought_prices[-1],
                }
            )
    return final_prices


def _change_by_lead_time(series: _Series, readings: list[CalendarReading]) -> list[dict]:
    """For each Lead Time, the average difference from the Opening Price,
    longest Lead Time first."""
    snapshot_dates = {reading.snapshot_date for reading in readings}
    changes: dict[int, list[int]] = defaultdict(list)
    for visit_date, sightings in series.items():
        opening = next(sighting for sighting in sightings if sighting.state != State.NOT_LISTED)
        opening_price = opening.bought_price
        # The Opening Price is known only if the Snapshot of the day before
        # was taken and did not list the Visit Date. Otherwise the Visit Date
        # may have opened at another price before anyone was looking, as with
        # every Visit Date already listed in the very first Snapshot.
        seen_opening = opening.snapshot_date - timedelta(days=1) in snapshot_dates
        if opening_price is None or not seen_opening:
            continue
        for sighting in sightings:
            lead_time = (visit_date - sighting.snapshot_date).days
            price = sighting.bought_price
            if price is not None and lead_time >= SHORTEST_LEAD_TIME:
                changes[lead_time].append(price - opening_price)
    return [
        {
            "lead_time": lead_time,
            "average_change": round(sum(changes[lead_time]) / len(changes[lead_time]), 2),
            "visit_dates": len(changes[lead_time]),
        }
        for lead_time in sorted(changes, reverse=True)
    ]


def _sku_changes(series: _Series) -> list[dict]:
    """Every Visit Date whose SKU differs from the one that priced it in the
    Snapshot before."""
    sku_changes = []
    for visit_date, sightings in series.items():
        priced = [sighting for sighting in sightings if sighting.sku_id is not None]
        for previous, sighting in pairwise(priced):
            if sighting.sku_id != previous.sku_id:
                sku_changes.append(
                    {
                        "visit_date": visit_date.isoformat(),
                        "snapshot_date": sighting.snapshot_date.isoformat(),
                        "sku_id": sighting.sku_id,
                        "previous_snapshot_date": previous.snapshot_date.isoformat(),
                        "previous_sku_id": previous.sku_id,
                    }
                )
    return sku_changes
