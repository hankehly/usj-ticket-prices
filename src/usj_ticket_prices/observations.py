"""Price Observations, derived from the stored responses of one Snapshot.

The stored responses are the source of truth. Nothing here is kept: every
build derives the Price Observations again from the full history.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from usj_ticket_prices.snapshot import check_response


@dataclass(frozen=True)
class PriceObservation:
    """The price of one product for one Guest Type on one Visit Date, in one Snapshot."""

    snapshot_date: date
    product_id: int
    # Normally one Guest Type. More than one when the store's own data
    # disagrees about the SKU, in which case the price cannot safely be given
    # to any one price series.
    guest_types: frozenset[str]
    visit_date: date
    sku_id: int
    price: int
    # False when the store lists the Visit Date but marks it not purchasable.
    purchasable: bool


@dataclass(frozen=True)
class CalendarReading:
    """One product's price calendar as one Snapshot saw it."""

    snapshot_date: date
    product_id: int
    product_title: str
    # Every Visit Date in the calendar, earliest first.
    visit_dates: list[date]
    observations: list[PriceObservation]


def read_price_calendar(
    snapshot_date: date, product_id: int, sku_list_body: bytes, price_calendar_body: bytes
) -> CalendarReading:
    product = check_response(sku_list_body)["data"]
    guest_types = _guest_types(product["sku"])

    calendar = check_response(price_calendar_body)["data"]
    # An empty calendar may arrive as a bare list rather than an object.
    entries = calendar.get("prices", []) if isinstance(calendar, dict) else []

    observations = []
    visit_dates = set()
    for entry in entries:
        visit_date = date.fromisoformat(entry["date"])
        visit_dates.add(visit_date)
        # The same goes for a Visit Date with no SKUs.
        skus = entry["sku"] if isinstance(entry["sku"], dict) else {}
        for sku_id, sku in skus.items():
            # An SKU the SKU list does not name has no Guest Type, so it
            # belongs to no price series.
            if int(sku_id) not in guest_types:
                continue
            observations.append(
                PriceObservation(
                    snapshot_date=snapshot_date,
                    product_id=product_id,
                    guest_types=guest_types[int(sku_id)],
                    visit_date=visit_date,
                    sku_id=int(sku_id),
                    price=_whole_number(sku["price"]),
                    purchasable=_is_on(entry["status"]) and _is_on(sku["status"]),
                )
            )
    return CalendarReading(
        snapshot_date=snapshot_date,
        product_id=product_id,
        product_title=str(product["title"]),
        visit_dates=sorted(visit_dates),
        observations=observations,
    )


def _guest_types(skus: list[dict]) -> dict[int, frozenset[str]]:
    """The Guest Types each SKU in an SKU list may stand for, by SKU id.

    An SKU's Guest Type is its label. For an SKU the store shows, that label
    is what a guest sees, so it is taken as given. Hidden SKUs are less
    trustworthy: some carry one Guest Type's label and another's type code.
    Such an SKU is given both Guest Types rather than a guess at either.
    """
    labels_by_type_code: dict[str, set[str]] = defaultdict(set)
    for sku in skus:
        if _is_shown(sku):
            labels_by_type_code[_type_code(sku)].add(_label(sku))

    guest_types = {}
    for sku in skus:
        labels = {_label(sku)}
        if not _is_shown(sku):
            labels |= labels_by_type_code.get(_type_code(sku), set())
        guest_types[int(sku["id"])] = frozenset(labels)
    return guest_types


def _label(sku: dict) -> str:
    # Hidden SKUs carry the same labels as shown ones, with stray spaces.
    return str(sku["title"]).strip()


def _type_code(sku: dict) -> str:
    return str(sku.get("user_type"))


def _is_shown(sku: dict) -> bool:
    return _is_on(sku.get("is_show", 1))


def _whole_number(value: object) -> int:
    """Read a number the store may send as either a number or a string.

    Raises ValueError for anything that is not a whole number, so that an
    unexpected format stops the build instead of being guessed at.
    """
    number = Decimal(str(value))
    if number != number.to_integral_value():
        raise ValueError(f"expected a whole number, got {value!r}")
    return int(number)


def _is_on(status: object) -> bool:
    # The store uses 1 for on. Any other value is read as off.
    return _whole_number(status) == 1
