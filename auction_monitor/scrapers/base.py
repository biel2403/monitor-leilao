from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from auction_monitor.models import RawLot


class AuctionScraper(ABC):
    source_name: str

    @abstractmethod
    def fetch_lots(self) -> Iterable[RawLot]:
        raise NotImplementedError

