from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from auction_monitor.models import RawLot
from auction_monitor.scrapers.base import AuctionScraper


class FixtureScraper(AuctionScraper):
    source_name = "fixture-local"

    def __init__(self, path: str):
        self.path = path

    def fetch_lots(self) -> Iterable[RawLot]:
        file_path = Path(self.path)
        if not file_path.exists():
            return []
        data = json.loads(file_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("Fixture deve conter uma lista de lotes")
        return [RawLot.from_dict(item, self.source_name) for item in data]

