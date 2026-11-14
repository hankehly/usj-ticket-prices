"""The official English web ticket store, read over its public API."""

from __future__ import annotations

import http.client
import time
import urllib.error
import urllib.request
from collections.abc import Callable

from usj_ticket_prices.snapshot import StoreError

BASE_URL = "https://www.usjticketing.com/api"
USER_AGENT = "usj-ticket-prices/0.1 (+https://github.com/hankehly/usj-ticket-prices)"
SECONDS_BETWEEN_REQUESTS = 3.0
TIMEOUT_SECONDS = 30

# The store's own numbering for its category pages.
PAGE_TYPES = {"studio-pass": 1, "express-pass": 2}


def _send(request: urllib.request.Request) -> bytes:
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read()


class HttpStore:
    """Reads the store one request at a time, never faster than the agreed pace."""

    def __init__(
        self,
        *,
        send: Callable[[urllib.request.Request], bytes] = _send,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._send = send
        self._sleep = sleep
        self._has_sent = False

    def product_list(self, category: str) -> bytes:
        return self._request("GET", f"/product/search?page_type={PAGE_TYPES[category]}")

    def sku_list(self, product_id: int) -> bytes:
        return self._request("GET", f"/product/sku?id={product_id}&photo_character_id=")

    def price_calendar(self, product_id: int) -> bytes:
        # A read-only lookup despite the POST. The query string carries the
        # parameters; the store ignores the body.
        return self._request(
            "POST", f"/product/sku-price?id={product_id}&photo_character_id="
        )

    def _request(self, method: str, path: str) -> bytes:
        if self._has_sent:
            self._sleep(SECONDS_BETWEEN_REQUESTS)
        self._has_sent = True
        request = urllib.request.Request(
            BASE_URL + path,
            method=method,
            data=b"" if method == "POST" else None,
            headers={"User-Agent": USER_AGENT, "lang": "en-US", "Accept": "application/json"},
        )
        try:
            return self._send(request)
        except urllib.error.HTTPError as error:
            raise StoreError(f"{method} {path} returned HTTP {error.code}") from error
        except http.client.HTTPException as error:
            # For example a response cut off mid-transfer. These are not
            # OSErrors, so without this they would crash the whole run.
            raise StoreError(f"{method} {path} failed: {error!r}") from error
