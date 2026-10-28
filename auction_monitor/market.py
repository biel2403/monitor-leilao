from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
import urllib.error
import urllib.request
from datetime import datetime, timezone

from auction_monitor.fipe import NoRedirect
from auction_monitor.scrapers.freitas import trusted_context


STATES = set("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())


def market_query(lot: dict, payload: dict) -> dict:
    make = str(payload.get("make") or "").strip().upper()
    model = str(payload.get("model") or "").strip().upper()
    region = str(payload.get("region") or "").strip().upper()
    if not 1 <= len(make) <= 60 or not 1 <= len(model) <= 80 or region and region not in STATES:
        raise ValueError("Confira marca, modelo e estado")
    year = lot.get("year")
    if not isinstance(year, int) or not 1900 <= year <= 2100:
        raise ValueError("Lote sem ano-modelo valido")
    query = {"vehicle_type": "car", "make": make, "model": model, "year_min": year, "year_max": year,
             "condition": "used", "armored": False, "page_size": 100, "page": 1, "sort": "relevance"}
    if region:
        query["location"] = region.lower()
    return query


def query_key(query: dict) -> str:
    return hashlib.sha256(json.dumps(query, sort_keys=True).encode()).hexdigest()


class MarketClient:
    def __init__(self, api_key: str | None):
        self.api_key = api_key

    def search(self, query: dict) -> dict:
        if not self.api_key:
            raise ValueError("Consulta de mercado nao configurada")
        request = urllib.request.Request(
            "https://api.reefapi.com/webmotors/v1/search",
            data=json.dumps(query).encode(),
            headers={"x-api-key": self.api_key, "Content-Type": "application/json"}, method="POST",
        )
        opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=trusted_context()))
        try:
            with opener.open(request, timeout=45) as response:
                envelope = json.load(response)
        except urllib.error.HTTPError as exc:
            message = {401: "Chave ReefAPI invalida", 402: "Creditos ReefAPI insuficientes", 403: "Acesso ReefAPI recusado", 429: "Limite da ReefAPI atingido"}
            raise ValueError(message.get(exc.code, "Consulta Webmotors indisponivel")) from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            raise ValueError("Nao foi possivel consultar a Webmotors agora") from None
        if not isinstance(envelope, dict) or envelope.get("ok") is not True:
            raise ValueError("O provedor nao concluiu a consulta Webmotors")
        return normalize_search(envelope, query)


def normalize_search(envelope: dict, query: dict) -> dict:
    data = envelope.get("data") or {}
    rows = data.get("listings") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError("Resposta de mercado incompleta")
    listings, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        identity = str(row.get("listing_id") or "")
        url = str(row.get("url") or "")
        if not identity or identity in seen or not re.match(r"^https://www\.webmotors\.com\.br/comprar/", url):
            continue
        try:
            price = float(row.get("price"))
            year = int(row.get("year_model"))
        except (TypeError, ValueError):
            continue
        seller = row.get("seller") or {}
        if (not math.isfinite(price) or not 1000 <= price <= 10000000 or year != query["year_min"]
                or str(row.get("make", "")).upper() != query["make"]
                or str(row.get("model", "")).upper() != query["model"]
                or row.get("armored") or row.get("condition_new") or row.get("has_auction_record")
                or query.get("location") and str(seller.get("state_code", "")).lower() != query["location"]):
            continue
        trim = str(row.get("trim") or "").strip()
        if not trim:
            continue
        seen.add(identity)
        listings.append({"id": identity, "url": url, "title": str(row.get("title") or ""),
                         "trim": trim, "year": year, "price": price, "mileage_km": row.get("mileage_km"),
                         "city": str(seller.get("city") or ""), "state": str(seller.get("state_code") or "")})
    meta = envelope.get("meta") or {}
    return {"query": query, "listings": listings, "collected_at": datetime.now(timezone.utc).isoformat(),
            "total_results": meta.get("total_results"), "has_more": bool((meta.get("pagination") or {}).get("has_more")),
            "charged_credits": meta.get("charged_credits"), "source": "Webmotors via ReefAPI"}


def summarize_market(search: dict, trim: str) -> dict:
    rows = [row for row in search["listings"] if row["trim"] == trim]
    if not rows:
        raise ValueError("Selecione uma versao retornada pela consulta")
    prices = sorted(row["price"] for row in rows)
    original_count = len(rows)
    # IQR only applies once the selected version has enough observations.
    if len(prices) >= 4:
        q1, _, q3 = statistics.quantiles(prices, n=4, method="inclusive")
        if q3 > q1:
            low, high = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
            rows = [row for row in rows if low <= row["price"] <= high]
            prices = sorted(row["price"] for row in rows)
    return {"source": search["source"], "query": search["query"], "trim": trim,
            "collected_at": search["collected_at"], "sample_count": len(rows), "excluded_count": original_count - len(rows),
            "median": statistics.median(prices) if len(prices) >= 3 else None,
            "minimum": min(prices), "maximum": max(prices), "listings": rows,
            "status": "referencia" if len(prices) >= 3 else "amostra_insuficiente",
            "has_more": search["has_more"], "total_results": search["total_results"],
            "note": "Precos anunciados, sem ajuste por quilometragem ou passagem por leilao. Nao representam vendas concluidas."}
