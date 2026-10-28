from __future__ import annotations

import re
import statistics
import unicodedata
from collections import defaultdict
from datetime import datetime
from typing import Any


RISK_WORDS = ("SUCATA", "SINISTRO", "SEGURADORA", "PEQUENA MONTA", "MEDIA MONTA", "DESMONTADO")
BRAND_ALIASES = {"CHEV": "CHEVROLET", "GM": "CHEVROLET"}
CONDITION_RED_FLAGS = {
    "DANOS ESTRUTURAIS": "Dano estrutural declarado",
    "CABECOTE DANIFICADO": "Cabeçote danificado",
    "AGUA NO CARTER": "Água no cárter",
    "ARREFECIMENTO DANIFICADO": "Arrefecimento danificado",
    "MOTOR E CAMBIO DESMONTADO": "Motor e câmbio desmontados",
    "MOTOR DESMONTADO": "Motor desmontado",
    "CAMBIO DESMONTADO": "Câmbio desmontado",
    "FREIO DANIFICADO": "Freio danificado",
    "SUSPENSAO DANIFICADA": "Suspensão danificada",
    "CORRENTE DANIFICADA": "Corrente danificada",
    "FALTANDO ETIQ": "Identificação incompleta",
    "SEM PLACAS": "Sem placas",
}


def price(lot: dict[str, Any]) -> float | None:
    value = lot.get("current_bid")
    if value is None:
        value = lot.get("initial_value")
    return float(value) if value is not None and float(value) > 0 else None


def vehicle_group(lot: dict[str, Any]) -> tuple[str, str] | None:
    title = str(lot.get("title") or "").upper().removeprefix("I/")
    if "/" not in title:
        return None
    brand, remainder = title.split("/", 1)
    brand = BRAND_ALIASES.get(brand.strip(), brand.strip())
    model = re.match(r"[A-Z0-9.-]+", remainder.strip())
    if not brand or not model:
        return None
    model_name = model.group(0)
    if model_name in {"CG", "CB", "XRE", "BIZ"}:
        displacement = re.search(r"\b(\d{2,3})\b", remainder[model.end():].split(",", 1)[0])
        if displacement:
            model_name += " " + displacement.group(1)
    if model_name == "ONIX" and remainder[model.end():].lstrip().startswith("PLUS"):
        model_name += " PLUS"
    return brand, model_name


def normalized(value: str) -> str:
    return "".join(character for character in unicodedata.normalize("NFKD", value.upper()) if not unicodedata.combining(character))


def specific_conditions(value: str) -> str:
    text = normalized(value)
    return text.split("VEICULO VENDIDO NO ESTADO", 1)[0]


def condition_red_flags(value: str) -> list[str]:
    specific = specific_conditions(value)
    return [label for phrase, label in CONDITION_RED_FLAGS.items() if phrase in specific]


def rank_candidates(
    lots: list[dict[str, Any]],
    now: datetime | None = None,
    limit: int = 20,
    details: dict[int, dict[str, Any]] | None = None,
    verified_only: bool = False,
) -> list[dict[str, Any]]:
    now = now or datetime.now()
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    eligible = []
    for lot in lots:
        group = vehicle_group(lot)
        title = normalized(str(lot.get("title") or ""))
        if not group or not lot.get("year") or price(lot) is None:
            continue
        if any(word in title for word in RISK_WORDS):
            continue
        if "ABERTO" not in str(lot.get("status") or "").upper():
            continue
        closes_at = lot.get("closes_at")
        if not closes_at:
            continue
        try:
            if datetime.fromisoformat(str(closes_at)) <= now:
                continue
        except ValueError:
            continue
        eligible.append((lot, group))
        groups[(str(lot.get("source_site")), *group)].append(lot)

    ranked = []
    for lot, group in eligible:
        detail = (details or {}).get(int(lot["id"]))
        if verified_only and (not detail or not detail.get("condition_text")):
            continue
        if detail and any(word in normalized(str(detail["classification"])) for word in RISK_WORDS):
            continue
        peers = [
            other for other in groups[(str(lot.get("source_site")), *group)]
            if other.get("id") != lot.get("id") and abs(int(other["year"]) - int(lot["year"])) <= 1
        ]
        if len(peers) < 3:
            continue
        peer_median = statistics.median(price(other) for other in peers)
        current = price(lot)
        known_total = round(current * (1 + float(detail["commission_percent"]) / 100) + float(detail["fixed_fees"]), 2) if detail else current
        below = round((peer_median - known_total) / peer_median * 100, 1)
        if below < 12:
            continue
        red_flags = condition_red_flags(str(detail.get("condition_text") or "")) if detail else []
        ranked.append({
            "lot_id": lot["id"],
            "title": lot["title"],
            "url": lot["url"],
            "source_site": lot["source_site"],
            "current_price": current,
            "known_total": known_total if detail else None,
            "classification": detail["classification"] if detail else None,
            "commission_percent": detail["commission_percent"] if detail else None,
            "fixed_fees": detail["fixed_fees"] if detail else None,
            "peer_median": peer_median,
            "below_peers_percent": below,
            "peer_count": len(peers),
            "group": f"{group[0]} {group[1]} {lot['year']}",
            "closes_at": closes_at,
            "red_flags": red_flags,
            "screening_status": "descartado" if red_flags else "pendente",
            "notice_url": detail.get("notice_url") if detail else None,
            "note": "Total inclui comissao e despesas publicadas; outros custos e estado devem ser verificados.",
        })
    ranked.sort(key=lambda item: (bool(item["red_flags"]), -item["below_peers_percent"], -item["peer_count"], item["current_price"]))
    return ranked[:limit]
