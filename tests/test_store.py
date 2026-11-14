import http.client
import urllib.error

import pytest

from usj_ticket_prices.snapshot import StoreError
from usj_ticket_prices.store import HttpStore


class Wire:
    """Stands in for the network: records requests and the pauses between them."""

    def __init__(self) -> None:
        self.events: list[object] = []

    def send(self, request) -> bytes:
        self.events.append(request)
        return b'{"status":1,"msg":"","data":[]}'

    def sleep(self, seconds: float) -> None:
        self.events.append(seconds)

    @property
    def requests(self):
        return [event for event in self.events if not isinstance(event, float)]


def test_requests_are_spaced_three_seconds_apart():
    wire = Wire()
    store = HttpStore(send=wire.send, sleep=wire.sleep)

    store.product_list("studio-pass")
    store.sku_list(139)
    store.price_calendar(139)

    kinds = ["pause" if isinstance(event, float) else "request" for event in wire.events]
    assert kinds == ["request", "pause", "request", "pause", "request"]
    assert [event for event in wire.events if isinstance(event, float)] == [3.0, 3.0]


def test_requests_identify_the_project():
    wire = Wire()

    HttpStore(send=wire.send, sleep=wire.sleep).sku_list(139)

    (request,) = wire.requests
    assert "usj-ticket-prices" in request.get_header("User-agent")
    assert "github.com/hankehly/usj-ticket-prices" in request.get_header("User-agent")
    assert request.get_header("Lang") == "en-US"


def test_each_reading_uses_the_stores_endpoint_for_it():
    wire = Wire()
    store = HttpStore(send=wire.send, sleep=wire.sleep)

    store.product_list("studio-pass")
    store.product_list("express-pass")
    store.sku_list(139)
    store.price_calendar(139)

    api = "https://www.usjticketing.com/api"
    assert [(r.get_method(), r.full_url) for r in wire.requests] == [
        ("GET", f"{api}/product/search?page_type=1"),
        ("GET", f"{api}/product/search?page_type=2"),
        ("GET", f"{api}/product/sku?id=139&photo_character_id="),
        ("POST", f"{api}/product/sku-price?id=139&photo_character_id="),
    ]


def test_an_http_error_is_a_store_error():
    def refuse(request):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", None, None)

    store = HttpStore(send=refuse, sleep=lambda seconds: None)

    with pytest.raises(StoreError, match="403"):
        store.sku_list(139)


def test_a_response_cut_off_mid_transfer_is_a_store_error():
    def cut_off(request):
        raise http.client.IncompleteRead(b'{"status":1,"da')

    store = HttpStore(send=cut_off, sleep=lambda seconds: None)

    with pytest.raises(StoreError, match="IncompleteRead"):
        store.price_calendar(139)
