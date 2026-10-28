from __future__ import annotations

from typing import Any

from auction_monitor.filtering import calculate_discount_percent, matches_filter


def analyze_lot(lot: dict[str, Any], filter_row: dict[str, Any]) -> dict[str, Any] | None:
    criteria = filter_row.get("criteria") or {}
    matches, matched_criteria = matches_filter(lot, criteria)
    if not matches:
        return None
    discount = calculate_discount_percent(lot.get("reference_value"), lot.get("current_bid") or lot.get("initial_value"))
    return {
        "lot_id": lot["id"],
        "filter_id": filter_row["id"],
        "matched_criteria": matched_criteria,
        "discount_percent": discount,
    }

