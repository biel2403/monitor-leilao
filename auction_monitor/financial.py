from __future__ import annotations

from decimal import Decimal, ROUND_DOWN
from typing import Any


MOTORCYCLE_BRANDS = {
    "APRILIA", "BAJAJ", "BENELLI", "DUCATI", "HARLEY DAVIDSON", "HARLEY",
    "HUSQVARNA", "INDIAN", "JTZ", "KAWASAKI", "KTM", "MV AGUSTA", "RE", "ROYAL ENFIELD",
    "SHINERAY", "SR", "TRIUMPH", "YAMAHA", "ZERO",
}
HONDA_MOTORCYCLES = ("CG", "CB", "XRE", "BIZ", "PCX", "NX-4", "NXR", "ELITE")


def is_car(lot: dict[str, Any]) -> bool:
    title = str(lot.get("title") or "").upper().removeprefix("I/")
    brand, _, rest = title.partition("/")
    model = rest.strip().split(maxsplit=1)[0] if rest.strip() else ""
    if brand in MOTORCYCLE_BRANDS:
        return False
    return not (brand == "HONDA" and model.startswith(HONDA_MOTORCYCLES))


def max_bid_for_resale(fipe_value: float, model_year: int, commission_percent: float, fixed_fees: float) -> dict[str, Any]:
    if fipe_value <= 0 or model_year <= 0 or commission_percent < 0 or fixed_fees < 0:
        raise ValueError("Dados financeiros invalidos")
    discount_percent = 30 if model_year < 2020 else 20
    fipe = Decimal(str(fipe_value))
    discount = Decimal(discount_percent) / 100
    fees = Decimal(str(fixed_fees))
    commission = Decimal(str(commission_percent)) / 100
    ceiling = ((fipe * (1 - discount) - fees) / (1 + commission)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    return {"discount_percent": discount_percent, "max_bid": max(0.0, float(ceiling))}


def assess_resale(
    lot: dict[str, Any],
    detail: dict[str, Any],
    reference: dict[str, Any] | None,
) -> dict[str, Any]:
    if not reference or not lot.get("year"):
        year = lot.get("year")
        return {"status": "sem_fipe", "discount_percent": (30 if year < 2020 else 20) if year else None}
    calculation = max_bid_for_resale(
        float(reference["fipe_value"]),
        int(lot["year"]),
        float(detail["commission_percent"]),
        float(detail["fixed_fees"]),
    )
    current_bid = lot.get("current_bid") or lot.get("initial_value")
    if current_bid is None:
        return {**calculation, "status": "sem_lance", "reference": reference}
    return {
        **calculation,
        "status": "dentro_teto" if float(current_bid) <= calculation["max_bid"] else "acima_teto",
        "reference": reference,
        "headroom": round(calculation["max_bid"] - float(current_bid), 2),
    }
