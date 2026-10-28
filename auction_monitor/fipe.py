from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher
import urllib.error
import urllib.request

from auction_monitor.scrapers.freitas import trusted_context


BASE_URL = "https://fipe.parallelum.com.br/api/v2"
BRAND_ALIASES = {
    "CHEV": "CHEVROLET", "GM": "CHEVROLET", "VW": "VW VOLKSWAGEN",
    "M BENZ": "MERCEDES BENZ", "MMC": "MITSUBISHI", "LR": "LAND ROVER",
    "CAOACHERY": "CHERY", "JAC": "JAC MOTORS",
}
MODEL_TOKEN_ALIASES = {
    "AF": ("AUT", "FLEX"),
    "AT": ("AUT",),
    "CL": ("COMFORTLINE",),
    "HL": ("HIGHLINE",),
    "LNGTD": ("LONGITUDE",),
    "LGTD": ("LONGITUDE",),
    "MT": ("MANUAL",),
}


def normalized(value: str) -> str:
    plain = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[A-Z0-9]+", plain.upper()))


def catalog_name(row: dict) -> str:
    return str(row.get("label") or row.get("name") or "")


def auction_identity(title: str) -> tuple[str, str]:
    raw = re.sub(r"^(?:I|IMP)/", "", str(title).upper()).split(",", 1)[0]
    raw = normalized(raw)
    parts = raw.split()
    if not parts:
        raise ValueError("Anuncio sem identificacao do veiculo")
    brand_token, model_start = ("M BENZ", 2) if parts[:2] == ["M", "BENZ"] else (parts[0], 1)
    brand = BRAND_ALIASES.get(brand_token, brand_token)
    model = " ".join(parts[model_start:])
    if not model:
        raise ValueError("Modelo nao identificado no anuncio")
    return brand, model


def best_catalog_match(query: str, rows: list[dict], minimum: float = 0.42) -> list[dict]:
    raw_tokens = normalized(query).split()
    expanded_tokens = []
    for token in raw_tokens:
        expanded_tokens.extend(MODEL_TOKEN_ALIASES.get(token, (token,)))
    query_tokens = set(expanded_tokens)
    if not query_tokens:
        raise ValueError("Modelo nao identificado no anuncio")
    base = raw_tokens[0]
    scored = []
    for row in rows:
        label = normalized(catalog_name(row))
        tokens = set(label.split())
        if base not in tokens:
            continue
        overlap = len(query_tokens & tokens) / max(1, len(query_tokens))
        ratio = SequenceMatcher(None, " ".join(expanded_tokens), label).ratio()
        score = overlap * 0.75 + ratio * 0.25
        scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored or scored[0][0] < minimum:
        raise ValueError("Nao foi possivel identificar com seguranca a versao FIPE")
    best_score = scored[0][0]
    likely = [item for item in scored if item[0] >= max(minimum, best_score - 0.16)]
    return [{**row, "match_score": score} for score, row in likely[:20]]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class FipeClient:
    def __init__(self, token: str | None = None):
        self.token = token

    def get(self, path: str):
        if not re.fullmatch(r"cars/brands(?:/\d+/models(?:/\d+/years(?:/\d{4,5}-\d+)?)?)?", path):
            raise ValueError("Consulta FIPE invalida")
        headers = {"Accept": "application/json", "User-Agent": "AuctionMonitor/1.0"}
        if self.token:
            headers["X-Subscription-Token"] = self.token
        request = urllib.request.Request(f"{BASE_URL}/{path}", headers=headers)
        opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=trusted_context()))
        try:
            with opener.open(request, timeout=20) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            messages = {401: "Token FIPE invalido", 403: "Acesso FIPE recusado", 404: "Veiculo nao encontrado", 429: "Limite de consultas FIPE atingido"}
            raise ValueError(messages.get(exc.code, f"Servico FIPE indisponivel (HTTP {exc.code})")) from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            raise ValueError("Nao foi possivel consultar o servico FIPE") from None

    def vehicle(self, brand: str, model: str, year: str) -> dict:
        data = self.get(f"cars/brands/{brand}/models/{model}/years/{year}")
        if not isinstance(data, dict) or not all(key in data for key in ("price", "model", "modelYear", "referenceMonth", "codeFipe")):
            raise ValueError("Resposta FIPE incompleta")
        if str(data["modelYear"]) != year.split("-", 1)[0]:
            raise ValueError("Ano retornado pela FIPE nao corresponde ao solicitado")
        price = str(data["price"]).replace("R$", "").replace(".", "").replace(",", ".").strip()
        try:
            value = float(price)
            if not 0 < value < 100000000:
                raise ValueError
        except ValueError:
            raise ValueError("Valor FIPE invalido") from None
        return {**data, "value": value, "source_url": f"{BASE_URL}/cars/brands/{brand}/models/{model}/years/{year}"}
