from __future__ import annotations

import json
import time
import urllib.request
from collections.abc import Iterable

from auction_monitor.models import RawLot
from auction_monitor.scrapers.base import AuctionScraper


class HttpJsonScraper(AuctionScraper):
    def __init__(self, source_name: str, url: str, timeout_seconds: int = 20, delay_seconds: float = 1.0):
        self.source_name = source_name
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.delay_seconds = delay_seconds

    def fetch_lots(self) -> Iterable[RawLot]:
        time.sleep(self.delay_seconds)
        request = urllib.request.Request(self.url, headers={"User-Agent": "auction-monitor/0.1"})
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        items = payload.get("lots", payload) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise ValueError("Resposta JSON deve conter lista de lotes")
        return [RawLot.from_dict(item, self.source_name) for item in items]

