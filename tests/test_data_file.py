import json
from datetime import UTC, date, datetime, time, timedelta

from tests.fakes import InMemoryArchive, fixture
from usj_ticket_prices.data_file import build_data_file

ADULT, CHILD, SENIOR = 30831, 30832, 30833
HIDDEN_ADULT = 30834  # Not shown in the store, but also labelled Adult.
# Not shown in the store, labelled Child, but carrying the Adult type code.
HIDDEN_CHILD_CODED_ADULT = 30835


def day(visit_date: str, skus: dict, *, status: object = 1) -> dict:
    """One Visit Date of a price calendar, shaped as the store returns it.

    `skus` maps an SKU id to its price, or to the fields that differ from a
    purchasable SKU.
    """
    entries = {}
    for sku_id, fields in skus.items():
        if not isinstance(fields, dict):
            fields = {"price": fields}
        entries[str(sku_id)] = {
            "date": visit_date,
            "use_at": f"{visit_date} 00:00:00",
            "end_at": None,
            "session_id": "",
            "status": 1,
            "min_num": 0,
            "sort": 0,
            "max_num": 4,
            **fields,
        }
    prices = [entry["price"] for entry in entries.values()]
    price = prices[0] if prices else 0
    return {"date": visit_date, "price": price, "status": status, "sku": entries}


def calendar(*days: dict) -> bytes:
    data = {"ticket_type": 1, "ticket_sell_deadline": "", "prices": list(days)}
    return json.dumps({"status": 1, "msg": "", "data": data}).encode()


def store_snapshot(
    archive: InMemoryArchive,
    snapshot_date: str,
    price_calendar: bytes,
    *,
    sku_list: bytes | None = None,
) -> None:
    """Store the 1 Day Studio Pass responses of one Snapshot, fetched at 04:00 Japan time."""
    day_ = date.fromisoformat(snapshot_date)
    fetched_at = datetime.combine(day_, time(19, 0, 7), UTC) - timedelta(days=1)
    archive.write(day_, "sku-list/139.json", sku_list or fixture("sku-list-139.json"), fetched_at)
    archive.write(day_, "price-calendar/139.json", price_calendar, fetched_at)


def built(archive: InMemoryArchive) -> dict:
    return json.loads(build_data_file(archive))


def test_upcoming_prices_are_the_adult_prices_of_the_latest_snapshot():
    archive = InMemoryArchive()
    store_snapshot(archive, "2026-11-15", fixture("price-calendar-139.json"))

    data = built(archive)

    assert data["product"] == {"id": 139, "title": "1 Day Studio Pass"}
    assert data["guest_type"] == "Adult"
    assert data["latest_snapshot"] == {
        "date": "2026-11-15",
        "taken_at": "2026-11-14T19:00:07+00:00",
    }
    upcoming = data["upcoming_prices"]
    assert upcoming[0] == {"visit_date": "2026-11-15", "state": "available", "price": 11900}
    assert upcoming[2] == {"visit_date": "2026-11-17", "state": "available", "price": 9900}
    assert upcoming[-1]["visit_date"] == "2027-01-15"
    # 62 days from the Snapshot date to the last one listed, one of them Not Listed.
    assert len(upcoming) == 62


def test_a_visit_date_missing_from_the_calendar_is_not_listed():
    archive = InMemoryArchive()
    store_snapshot(archive, "2026-11-15", fixture("price-calendar-139.json"))

    upcoming = built(archive)["upcoming_prices"]

    assert upcoming[1] == {"visit_date": "2026-11-16", "state": "not_listed", "price": None}
    assert [entry["state"] for entry in upcoming].count("not_listed") == 1


def test_numbers_the_store_sends_as_strings_are_read_as_numbers():
    archive = InMemoryArchive()
    stringly = day("2026-11-15", {ADULT: {"price": "11900", "status": "1"}}, status="1")
    store_snapshot(archive, "2026-11-15", calendar(stringly))

    assert built(archive)["upcoming_prices"] == [
        {"visit_date": "2026-11-15", "state": "available", "price": 11900}
    ]


def test_a_calendar_out_of_date_order_is_read_in_date_order():
    archive = InMemoryArchive()
    store_snapshot(
        archive,
        "2026-11-15",
        calendar(
            day("2026-11-17", {ADULT: 9900}),
            day("2026-11-15", {ADULT: 11900}),
            day("2026-11-16", {ADULT: 10400}),
        ),
    )

    upcoming = built(archive)["upcoming_prices"]

    assert [(entry["visit_date"], entry["price"]) for entry in upcoming] == [
        ("2026-11-15", 11900),
        ("2026-11-16", 10400),
        ("2026-11-17", 9900),
    ]


def test_a_visit_date_marked_not_purchasable_is_unavailable_not_not_listed():
    archive = InMemoryArchive()
    store_snapshot(
        archive,
        "2026-11-15",
        calendar(
            day("2026-11-15", {ADULT: {"price": 11900, "status": 0}}),
            day("2026-11-16", {ADULT: 10400}, status=0),
            day("2026-11-18", {ADULT: 9900}),
        ),
    )

    upcoming = built(archive)["upcoming_prices"]

    assert upcoming == [
        {"visit_date": "2026-11-15", "state": "unavailable", "price": 11900},
        {"visit_date": "2026-11-16", "state": "unavailable", "price": 10400},
        {"visit_date": "2026-11-17", "state": "not_listed", "price": None},
        {"visit_date": "2026-11-18", "state": "available", "price": 9900},
    ]


def test_a_visit_date_listed_without_an_adult_price_is_unavailable():
    archive = InMemoryArchive()
    store_snapshot(
        archive,
        "2026-11-15",
        calendar(day("2026-11-15", {CHILD: 7400}), day("2026-11-16", {ADULT: 10400, CHILD: 6800})),
    )

    assert built(archive)["upcoming_prices"] == [
        {"visit_date": "2026-11-15", "state": "unavailable", "price": None},
        {"visit_date": "2026-11-16", "state": "available", "price": 10400},
    ]


def test_the_output_never_says_sold_out():
    archive = InMemoryArchive()
    store_snapshot(
        archive,
        "2026-11-15",
        calendar(day("2026-11-15", {ADULT: {"price": 11900, "status": 0}}), day("2026-11-17", {})),
    )

    assert "sold" not in build_data_file(archive).decode().lower()


def three_days() -> InMemoryArchive:
    archive = InMemoryArchive()
    store_snapshot(
        archive,
        "2026-11-15",
        calendar(day("2026-11-15", {ADULT: 11900}), day("2026-11-17", {ADULT: 9900})),
    )
    store_snapshot(
        archive,
        "2026-11-16",
        calendar(
            day("2026-11-16", {ADULT: 10400}),
            day("2026-11-17", {ADULT: 9900}),
            day("2026-11-18", {ADULT: 9400}),
        ),
    )
    store_snapshot(
        archive,
        "2026-11-17",
        calendar(
            day("2026-11-17", {ADULT: 10400}),
            day("2026-11-18", {ADULT: 9400}),
            day("2026-11-20", {ADULT: 9000}),
        ),
    )
    return archive


def test_each_visit_date_ever_observed_has_its_price_at_every_snapshot():
    histories = built(three_days())["histories"]

    def available(snapshot_date: str, price: int) -> dict:
        return {
            "snapshot_date": snapshot_date,
            "state": "available",
            "price": price,
            "sku_id": ADULT,
        }

    assert histories == {
        # Past Visit Dates stay, though the latest Snapshot no longer lists them.
        "2026-11-15": [available("2026-11-15", 11900)],
        "2026-11-16": [
            {
                "snapshot_date": "2026-11-15",
                "state": "not_listed",
                "price": None,
                "sku_id": None,
            },
            available("2026-11-16", 10400),
        ],
        "2026-11-17": [
            available("2026-11-15", 9900),
            available("2026-11-16", 9900),
            available("2026-11-17", 10400),
        ],
        "2026-11-18": [available("2026-11-16", 9400), available("2026-11-17", 9400)],
        # 2026-11-19 has never been listed, so it was never observed.
        "2026-11-20": [available("2026-11-17", 9000)],
    }


def test_final_prices_carry_the_weekday_of_every_visit_date_ever_observed():
    # 2026-11-15 is a Sunday. Weekdays are numbered from Monday = 1.
    assert built(three_days())["final_prices"] == [
        {"visit_date": "2026-11-15", "weekday": 7, "price": 11900},
        {"visit_date": "2026-11-16", "weekday": 1, "price": 10400},
        {"visit_date": "2026-11-17", "weekday": 2, "price": 10400},
        {"visit_date": "2026-11-18", "weekday": 3, "price": 9400},
        {"visit_date": "2026-11-20", "weekday": 5, "price": 9000},
    ]


def test_the_final_price_is_the_last_price_that_could_be_bought():
    archive = InMemoryArchive()
    store_snapshot(archive, "2026-11-15", calendar(day("2026-11-16", {ADULT: 10400})))
    store_snapshot(
        archive, "2026-11-16", calendar(day("2026-11-16", {ADULT: {"price": 0, "status": 0}}))
    )

    assert built(archive)["final_prices"] == [
        {"visit_date": "2026-11-16", "weekday": 1, "price": 10400}
    ]


def test_change_by_lead_time_averages_the_difference_from_the_opening_price():
    archive = InMemoryArchive()
    # Already listed in the very first Snapshot: Opening Price unknown.
    store_snapshot(archive, "2026-11-15", calendar(day("2026-11-16", {ADULT: 10000})))
    store_snapshot(
        archive,
        "2026-11-16",
        calendar(
            day("2026-11-16", {ADULT: 12000}),
            day("2026-11-19", {ADULT: 9000}),  # opens at a Lead Time of 3
            day("2026-11-20", {ADULT: 8000}),  # opens at a Lead Time of 4
        ),
    )
    store_snapshot(
        archive,
        "2026-11-17",
        calendar(day("2026-11-19", {ADULT: 9500}), day("2026-11-20", {ADULT: 8000})),
    )
    # 2026-11-19 is Not Listed at a Lead Time of 1.
    store_snapshot(archive, "2026-11-18", calendar(day("2026-11-20", {ADULT: 8600})))
    store_snapshot(
        archive,
        "2026-11-19",
        calendar(day("2026-11-19", {ADULT: 10000}), day("2026-11-20", {ADULT: 9000})),
    )

    assert built(archive)["change_by_lead_time"] == [
        {"lead_time": 4, "average_change": 0, "visit_dates": 1},
        {"lead_time": 3, "average_change": 0, "visit_dates": 2},
        {"lead_time": 2, "average_change": 550, "visit_dates": 2},
        # Only 2026-11-20 (+1000). A Lead Time of zero is never included.
        {"lead_time": 1, "average_change": 1000, "visit_dates": 1},
    ]


def test_change_by_lead_time_is_empty_while_no_opening_price_is_known():
    archive = InMemoryArchive()
    store_snapshot(archive, "2026-11-15", fixture("price-calendar-139.json"))

    assert built(archive)["change_by_lead_time"] == []


def test_a_change_of_sku_keeps_the_series_continuous_and_is_flagged():
    archive = InMemoryArchive()
    store_snapshot(archive, "2026-11-15", calendar(day("2026-11-15", {ADULT: 9000})))
    store_snapshot(archive, "2026-11-16", calendar(day("2026-11-20", {ADULT: 9000})))
    store_snapshot(archive, "2026-11-17", calendar(day("2026-11-20", {HIDDEN_ADULT: 9200})))
    store_snapshot(archive, "2026-11-18", calendar(day("2026-11-20", {HIDDEN_ADULT: 9200})))

    data = built(archive)

    assert [
        (entry["state"], entry["price"], entry["sku_id"])
        for entry in data["histories"]["2026-11-20"]
    ] == [
        ("available", 9000, ADULT),
        ("available", 9200, HIDDEN_ADULT),
        ("available", 9200, HIDDEN_ADULT),
    ]
    assert data["change_by_lead_time"][-2:] == [
        {"lead_time": 3, "average_change": 200, "visit_dates": 1},
        {"lead_time": 2, "average_change": 200, "visit_dates": 1},
    ]
    assert data["flags"]["sku_changes"] == [
        {
            "visit_date": "2026-11-20",
            "snapshot_date": "2026-11-17",
            "sku_id": HIDDEN_ADULT,
            "previous_snapshot_date": "2026-11-16",
            "previous_sku_id": ADULT,
        }
    ]
    assert data["flags"]["sku_conflicts"] == []


def test_two_skus_for_one_guest_type_on_one_visit_date_are_flagged_not_resolved():
    archive = InMemoryArchive()
    store_snapshot(
        archive,
        "2026-11-20",
        calendar(
            day("2026-11-20", {HIDDEN_ADULT: 9200, ADULT: 9000, CHILD: 6000}),
            day("2026-11-21", {ADULT: 9900}),
        ),
    )

    data = built(archive)

    assert data["upcoming_prices"] == [
        {"visit_date": "2026-11-20", "state": "sku_conflict", "price": None},
        {"visit_date": "2026-11-21", "state": "available", "price": 9900},
    ]
    assert data["histories"]["2026-11-20"] == [
        {"snapshot_date": "2026-11-20", "state": "sku_conflict", "price": None, "sku_id": None}
    ]
    assert data["final_prices"] == [{"visit_date": "2026-11-21", "weekday": 6, "price": 9900}]
    assert data["flags"]["sku_conflicts"] == [
        {
            "snapshot_date": "2026-11-20",
            "visit_date": "2026-11-20",
            "skus": [
                {"sku_id": ADULT, "price": 9000, "guest_types": ["Adult"]},
                {"sku_id": HIDDEN_ADULT, "price": 9200, "guest_types": ["Adult"]},
            ],
        }
    ]
    assert data["flags"]["sku_changes"] == []


def test_an_sku_whose_label_and_type_code_disagree_is_flagged_beside_the_adult_sku():
    archive = InMemoryArchive()
    store_snapshot(
        archive,
        "2026-11-20",
        calendar(day("2026-11-20", {ADULT: 9000, HIDDEN_CHILD_CODED_ADULT: 9200})),
    )

    data = built(archive)

    assert data["upcoming_prices"] == [
        {"visit_date": "2026-11-20", "state": "sku_conflict", "price": None}
    ]
    assert data["flags"]["sku_conflicts"] == [
        {
            "snapshot_date": "2026-11-20",
            "visit_date": "2026-11-20",
            "skus": [
                {"sku_id": ADULT, "price": 9000, "guest_types": ["Adult"]},
                {
                    "sku_id": HIDDEN_CHILD_CODED_ADULT,
                    "price": 9200,
                    "guest_types": ["Adult", "Child"],
                },
            ],
        }
    ]


def test_an_sku_whose_label_and_type_code_disagree_is_not_taken_as_the_adult_price():
    archive = InMemoryArchive()
    store_snapshot(
        archive, "2026-11-20", calendar(day("2026-11-20", {HIDDEN_CHILD_CODED_ADULT: 9200}))
    )

    data = built(archive)

    assert data["upcoming_prices"] == [
        {"visit_date": "2026-11-20", "state": "sku_conflict", "price": None}
    ]
    assert [flag["visit_date"] for flag in data["flags"]["sku_conflicts"]] == ["2026-11-20"]


def test_a_visit_date_that_opened_while_a_snapshot_was_missed_has_no_opening_price():
    archive = InMemoryArchive()
    store_snapshot(archive, "2026-11-15", calendar(day("2026-11-15", {ADULT: 9000})))
    # No Snapshot on 2026-11-16, so 2026-11-25 may have opened then at another price.
    store_snapshot(archive, "2026-11-17", calendar(day("2026-11-25", {ADULT: 9000})))
    store_snapshot(
        archive,
        "2026-11-18",
        calendar(day("2026-11-25", {ADULT: 9500}), day("2026-11-26", {ADULT: 8000})),
    )
    store_snapshot(
        archive,
        "2026-11-19",
        calendar(day("2026-11-25", {ADULT: 9500}), day("2026-11-26", {ADULT: 8300})),
    )

    assert built(archive)["change_by_lead_time"] == [
        {"lead_time": 8, "average_change": 0, "visit_dates": 1},
        {"lead_time": 7, "average_change": 300, "visit_dates": 1},
    ]


def test_building_twice_over_the_same_snapshots_gives_the_same_file():
    assert build_data_file(three_days()) == build_data_file(three_days())


def test_a_snapshot_without_the_products_price_calendar_is_passed_over():
    archive = three_days()
    incomplete = date(2026, 11, 18)
    fetched_at = datetime(2026, 11, 17, 19, tzinfo=UTC)
    archive.write(incomplete, "product-list/studio-pass.json", b"{}", fetched_at)
    archive.write(incomplete, "sku-list/139.json", fixture("sku-list-139.json"), fetched_at)

    data = built(archive)

    assert data["latest_snapshot"]["date"] == "2026-11-17"
    assert data == built(three_days())


def test_before_any_snapshot_the_file_is_valid_and_empty():
    assert built(InMemoryArchive()) == {
        "product": {"id": 139, "title": None},
        "guest_type": "Adult",
        "latest_snapshot": None,
        "upcoming_prices": [],
        "final_prices": [],
        "change_by_lead_time": [],
        "histories": {},
        "flags": {"sku_changes": [], "sku_conflicts": []},
    }


def test_an_empty_price_calendar_makes_every_date_listed_before_not_listed():
    for empty in (calendar(), b'{"status":1,"msg":"","data":[]}'):
        archive = three_days()
        store_snapshot(archive, "2026-11-18", empty)

        data = built(archive)

        assert data["latest_snapshot"]["date"] == "2026-11-18"
        # Earlier Snapshots listed dates up to 2026-11-20.
        assert data["upcoming_prices"] == [
            {"visit_date": "2026-11-18", "state": "not_listed", "price": None},
            {"visit_date": "2026-11-19", "state": "not_listed", "price": None},
            {"visit_date": "2026-11-20", "state": "not_listed", "price": None},
        ]
        assert [
            (entry["snapshot_date"], entry["state"]) for entry in data["histories"]["2026-11-20"]
        ] == [("2026-11-17", "available"), ("2026-11-18", "not_listed")]
        assert "2026-11-19" not in data["histories"]


def test_a_visit_date_dropped_from_a_shorter_calendar_is_not_listed_until_it_returns():
    archive = InMemoryArchive()
    store_snapshot(
        archive,
        "2026-11-15",
        calendar(day("2026-11-15", {ADULT: 11900}), day("2026-11-20", {ADULT: 9000})),
    )
    store_snapshot(archive, "2026-11-16", calendar(day("2026-11-16", {ADULT: 10400})))
    store_snapshot(
        archive,
        "2026-11-17",
        calendar(day("2026-11-17", {ADULT: 9900}), day("2026-11-20", {ADULT: 9500})),
    )

    history = built(archive)["histories"]["2026-11-20"]

    assert [(entry["snapshot_date"], entry["state"], entry["price"]) for entry in history] == [
        ("2026-11-15", "available", 9000),
        ("2026-11-16", "not_listed", None),
        ("2026-11-17", "available", 9500),
    ]


def test_an_sku_missing_from_the_sku_list_has_no_guest_type_and_is_left_out():
    archive = InMemoryArchive()
    store_snapshot(archive, "2026-11-15", calendar(day("2026-11-15", {ADULT: 11900, 99999: 100})))

    data = built(archive)

    assert data["upcoming_prices"] == [
        {"visit_date": "2026-11-15", "state": "available", "price": 11900}
    ]
    assert data["flags"]["sku_conflicts"] == []
