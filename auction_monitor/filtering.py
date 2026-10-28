from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def matches_filter(lot: dict[str, Any], criteria: dict[str, Any]) -> tuple[bool, list[str]]:
    matched: list[str] = []

    checks = [
        check_equal(lot, criteria, "category", "Categoria"),
        check_equal(lot, criteria, "state", "Estado"),
        check_equal(lot, criteria, "source_site", "Site de origem"),
        check_price(lot, criteria),
        check_year(lot, criteria),
        check_mileage(lot, criteria),
        check_list(lot, criteria, "brand", "brands", "Marca"),
        check_list(lot, criteria, "model", "models", "Modelo"),
        check_keywords(lot, criteria),
        check_time_remaining(lot, criteria),
        check_discount(lot, criteria),
    ]

    for ok, label, required in checks:
        if not ok:
            return False, matched
        if required and label:
            matched.append(label)
    return True, matched


def check_equal(lot: dict[str, Any], criteria: dict[str, Any], key: str, label: str) -> tuple[bool, str, bool]:
    expected = criteria.get(key)
    if expected in (None, ""):
        return True, label, False
    actual = lot.get(key)
    return normalize(actual) == normalize(expected), label, True


def check_price(lot: dict[str, Any], criteria: dict[str, Any]) -> tuple[bool, str, bool]:
    price = lot.get("current_bid") or lot.get("initial_value")
    min_price = criteria.get("min_price")
    max_price = criteria.get("max_price")
    if min_price is None and max_price is None:
        return True, "Preco", False
    if price is None:
        return False, "Preco", True
    if min_price is not None and float(price) < float(min_price):
        return False, "Preco minimo", True
    if max_price is not None and float(price) > float(max_price):
        return False, "Preco maximo", True
    labels = []
    if min_price is not None:
        labels.append("Preco minimo")
    if max_price is not None:
        labels.append("Preco maximo")
    return True, " e ".join(labels), True


def check_year(lot: dict[str, Any], criteria: dict[str, Any]) -> tuple[bool, str, bool]:
    year = lot.get("year")
    min_year = criteria.get("min_year")
    max_year = criteria.get("max_year")
    if min_year is None and max_year is None:
        return True, "Ano", False
    if year is None:
        return False, "Ano", True
    if min_year is not None and int(year) < int(min_year):
        return False, "Ano minimo", True
    if max_year is not None and int(year) > int(max_year):
        return False, "Ano maximo", True
    return True, "Ano", True


def check_mileage(lot: dict[str, Any], criteria: dict[str, Any]) -> tuple[bool, str, bool]:
    mileage = lot.get("mileage")
    max_mileage = criteria.get("max_mileage")
    if max_mileage is None:
        return True, "Quilometragem", False
    if mileage is None:
        return False, "Quilometragem", True
    return int(mileage) <= int(max_mileage), "Quilometragem", True


def check_list(lot: dict[str, Any], criteria: dict[str, Any], lot_key: str, criteria_key: str, label: str) -> tuple[bool, str, bool]:
    values = criteria.get(criteria_key)
    if not values:
        return True, label, False
    if isinstance(values, str):
        values = [values]
    actual_values = {normalize(lot.get(lot_key))}
    if lot_key == "brand":
        actual_values.add(normalize(brand_from_title(lot.get("title"))))
    return bool(actual_values & {normalize(value) for value in values}), label, True


def brand_from_title(title: Any) -> str:
    value = str(title or "")
    if value.startswith(("I/", "IMP/")):
        value = value.split("/", 1)[1]
    first_word = value.strip().split(maxsplit=1)[0] if value.strip() else ""
    brand = first_word.split("/", 1)[0].upper()
    aliases = {"CHEV": "CHEVROLET", "GM": "CHEVROLET", "LR": "LAND ROVER", "MMC": "MITSUBISHI", "M.BENZ": "MERCEDES-BENZ"}
    return aliases.get(brand, brand)


def check_keywords(lot: dict[str, Any], criteria: dict[str, Any]) -> tuple[bool, str, bool]:
    keywords = criteria.get("keywords")
    if not keywords:
        return True, "Palavras-chave", False
    if isinstance(keywords, str):
        keywords = [keywords]
    text = normalize(" ".join(str(lot.get(key) or "") for key in ("title", "description", "documentation", "damages", "restrictions")))
    return all(normalize(keyword) in text for keyword in keywords), "Palavras-chave", True


def check_time_remaining(lot: dict[str, Any], criteria: dict[str, Any]) -> tuple[bool, str, bool]:
    max_hours = criteria.get("max_hours_remaining")
    if max_hours is None:
        return True, "Tempo restante", False
    closes_at = lot.get("closes_at")
    if not closes_at:
        return False, "Tempo restante", True
    close_date = datetime.fromisoformat(str(closes_at))
    if close_date.tzinfo is None:
        close_date = close_date.replace(tzinfo=timezone.utc)
    remaining = (close_date - datetime.now(close_date.tzinfo)).total_seconds() / 3600
    return remaining <= float(max_hours), "Tempo restante", True


def check_discount(lot: dict[str, Any], criteria: dict[str, Any]) -> tuple[bool, str, bool]:
    min_discount = criteria.get("min_discount_percent")
    if min_discount is None:
        return True, "Desconto minimo", False
    discount = calculate_discount_percent(lot.get("reference_value"), lot.get("current_bid") or lot.get("initial_value"))
    if discount is None:
        return False, "Desconto minimo", True
    return discount >= float(min_discount), "Desconto minimo", True


def calculate_discount_percent(reference_value: Any, current_value: Any) -> float | None:
    if reference_value in (None, "") or current_value in (None, ""):
        return None
    reference = float(reference_value)
    current = float(current_value)
    if reference <= 0:
        return None
    return round(((reference - current) / reference) * 100, 2)


def normalize(value: Any) -> str:
    return str(value or "").strip().lower()
