from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def parse_datetime(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


@dataclass
class RawLot:
    title: str
    url: str
    external_id: str
    source_site: str
    description: str | None = None
    category: str | None = None
    brand: str | None = None
    model: str | None = None
    year: int | None = None
    mileage: int | None = None
    city: str | None = None
    state: str | None = None
    initial_value: float | None = None
    current_bid: float | None = None
    bid_count: int | None = None
    opens_at: str | None = None
    closes_at: str | None = None
    images: list[str] = field(default_factory=list)
    documentation: str | None = None
    damages: str | None = None
    accident: str | None = None
    financing: str | None = None
    restrictions: str | None = None
    auctioneer: str | None = None
    status: str | None = None
    reference_value: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any], default_source: str) -> "RawLot":
        title = str(data.get("title") or "").strip()
        url = str(data.get("url") or "").strip()
        external_id = str(data.get("external_id") or data.get("lot_id") or url).strip()
        source_site = str(data.get("source_site") or default_source).strip()
        if not title or not url or not external_id or not source_site:
            raise ValueError("title, url, external_id and source_site are required")
        images = data.get("images") or []
        if not isinstance(images, list):
            images = [str(images)]
        return cls(
            title=title,
            url=url,
            external_id=external_id,
            source_site=source_site,
            description=data.get("description"),
            category=data.get("category"),
            brand=data.get("brand"),
            model=data.get("model"),
            year=to_int(data.get("year")),
            mileage=to_int(data.get("mileage")),
            city=data.get("city") or data.get("location"),
            state=data.get("state"),
            initial_value=to_float(data.get("initial_value")),
            current_bid=to_float(data.get("current_bid")),
            bid_count=to_int(data.get("bid_count")),
            opens_at=parse_datetime(data.get("opens_at")),
            closes_at=parse_datetime(data.get("closes_at")),
            images=[str(image) for image in images],
            documentation=data.get("documentation"),
            damages=data.get("damages"),
            accident=data.get("accident"),
            financing=data.get("financing"),
            restrictions=data.get("restrictions"),
            auctioneer=data.get("auctioneer"),
            status=data.get("status"),
            reference_value=to_float(data.get("reference_value")),
        )

