from __future__ import annotations

import json
import logging
import mimetypes
import re
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from auction_monitor.ai_analysis import analyze_with_gemini, evidence_payload, fingerprint
from auction_monitor.config import Settings
from auction_monitor.database import Database
from auction_monitor.financial import assess_resale, is_car
from auction_monitor.fipe import FipeClient, auction_identity, best_catalog_match, catalog_name, normalized
from auction_monitor.market import MarketClient, market_query, query_key, summarize_market
from auction_monitor.service import MonitorService, SOURCES
from auction_monitor.scrapers.freitas import FreitasScraper

logger = logging.getLogger(__name__)
DEFAULT_CRITERIA = (
    "Objetivo: compra para revenda com margem. Para ano-modelo anterior a 2020, "
    "usar FIPE exata menos 30%; para 2020 em diante, FIPE exata menos 20%, "
    "inclusive Jetta, Nivus e T-Cross. Descontar comissao do leiloeiro e despesas "
    "administrativas do lance maximo. Sem FIPE da versao e ano corretos, nao aprovar. "
    "Avarias graves declaradas exigem descarte ou investigacao, nunca aprovacao automatica."
)


class ApiServer:
    def __init__(self, settings: Settings, db: Database, service: MonitorService):
        self.settings = settings
        self.db = db
        self.service = service

    def serve(self) -> None:
        handler = self._build_handler()
        server = ThreadingHTTPServer((self.settings.host, self.settings.port), handler)
        logger.info("Servidor iniciado em http://%s:%s", self.settings.host, self.settings.port)
        server.serve_forever()

    def _build_handler(self):
        settings = self.settings
        db = self.db
        service = self.service
        ai_lock = threading.Lock()
        market_lock = threading.Lock()
        market_client = MarketClient(settings.reef_api_key)
        fipe_client = FipeClient(settings.fipe_api_token)
        fipe_lock = threading.Lock()
        fipe_cache = {}

        def cached_fipe(key, fetch):
            with fipe_lock:
                cached = fipe_cache.get(key)
                if cached and time.monotonic() - cached[0] < 86400:
                    return cached[1]
                result = fetch()
                fipe_cache[key] = (time.monotonic(), result)
                return result

        def automatic_fipe(lot):
            brand_name, model_query = auction_identity(lot["title"])
            brands = cached_fipe("cars/brands", lambda: fipe_client.get("cars/brands"))
            brand = next((row for row in brands if normalized(catalog_name(row)) == brand_name), None)
            if brand is None:
                brand = next((row for row in brands if brand_name in normalized(catalog_name(row))), None)
            if brand is None:
                raise ValueError(f"Marca {brand_name} nao encontrada na FIPE")
            brand_code = str(brand["code"])
            models_path = f"cars/brands/{brand_code}/models"
            models = cached_fipe(models_path, lambda: fipe_client.get(models_path))
            candidates = best_catalog_match(model_query, models)
            target_year = str(lot.get("year") or "")
            if not re.fullmatch(r"\d{4}", target_year):
                raise ValueError("Ano-modelo nao identificado no anuncio")
            title = normalized(lot["title"])
            matches = []
            for candidate in candidates:
                model_code = str(candidate["code"])
                years_path = f"cars/brands/{brand_code}/models/{model_code}/years"
                years = cached_fipe(years_path, lambda path=years_path: fipe_client.get(path))
                matching = [row for row in years if str(row.get("code") or "").startswith(f"{target_year}-")]
                if "DIESEL" in title:
                    matching.sort(key=lambda row: "DIESEL" not in normalized(catalog_name(row)))
                else:
                    matching.sort(key=lambda row: "DIESEL" in normalized(catalog_name(row)))
                if not matching:
                    continue
                year_code = str(matching[0]["code"])
                vehicle_key = f"vehicle/{brand_code}/{model_code}/{year_code}"
                result = cached_fipe(vehicle_key, lambda: fipe_client.vehicle(brand_code, model_code, year_code))
                matches.append({**result, "match_score": candidate["match_score"]})
            if matches:
                # A menor FIPE compativel evita superestimar a margem quando o anuncio omite a versao.
                return min(matches, key=lambda row: row["value"])
            raise ValueError("A versao encontrada nao possui o ano-modelo informado no anuncio")

        def review_item(lot, details, references, analyses, market):
            lot_id = lot["id"]
            detail = details.get(lot_id)
            reference = references.get(lot_id)
            analysis = analyses.get(lot_id)
            financial = assess_resale(lot, detail, reference) if detail else {"status": "sem_detalhes"}
            financial["market_reference"] = market.get(lot_id)
            current = None
            if detail:
                stamp = fingerprint(
                    db.get_review_criteria() or DEFAULT_CRITERIA,
                    settings.gemini_model,
                    evidence_payload(lot, detail, financial),
                )
                if analysis and analysis["input_fingerprint"] == stamp:
                    current = analysis["result"]
            closes_at = lot.get("closes_at")
            active = True
            if closes_at:
                try:
                    parsed_close = datetime.fromisoformat(closes_at.replace("Z", "+00:00"))
                    now = datetime.now(timezone.utc) if parsed_close.tzinfo else datetime.now()
                    active = parsed_close > now
                except ValueError:
                    active = False
            approved = bool(active and current and current.get("decision") == "potencial" and financial.get("status") == "dentro_teto")
            return {
                **lot,
                "detail": detail,
                "fipe_reference": reference,
                "market": market.get(lot_id),
                "market_supported": is_car(lot),
                "analysis_supported": is_car(lot),
                "financial": financial,
                "ai_analysis": current,
                "analysis_status": "bom_negocio" if approved else (current.get("decision") if current else "nao_analisado"),
            }

        class Handler(BaseHTTPRequestHandler):
            def do_HEAD(self) -> None:
                path = urlparse(self.path).path
                if path in {"/", "/api/health"}:
                    self.send_response(HTTPStatus.OK)
                    self.end_headers()
                    return
                self.send_error(HTTPStatus.NOT_FOUND)

            def do_GET(self) -> None:
                path = urlparse(self.path).path
                if path == "/":
                    self.serve_static("dist/index.html" if (Path("web") / "dist/index.html").exists() else "index.html", "text/html; charset=utf-8")
                elif path.startswith("/assets/"):
                    self.serve_static(f"dist{path}", mimetypes.guess_type(path)[0] or "application/octet-stream")
                elif path == "/web/styles.css":
                    self.serve_static("styles.css", "text/css; charset=utf-8")
                elif path == "/main.jsx":
                    self.serve_static("main.jsx", "application/javascript; charset=utf-8")
                elif path == "/react.css":
                    self.serve_static("react.css", "text/css; charset=utf-8")
                elif path == "/api/health":
                    self.send_json({"status": "ok"})
                elif path == "/api/lots":
                    details = db.list_lot_details()
                    references = db.list_valuation_references()
                    analyses = db.list_ai_analyses()
                    market = db.list_market_references()
                    self.send_json({"items": [review_item(lot, details, references, analyses, market) for lot in db.list_lots()]})
                elif path == "/api/sources":
                    self.send_json({"items": [{"key": key, **source} for key, source in SOURCES.items()], "selected": db.selected_source()})
                elif path == "/api/candidates":
                    source = db.selected_source()
                    source_name = "fixture-local" if source == "sample" else SOURCES[source]["name"]
                    lots = [lot for lot in db.list_lots() if lot["source_site"] == source_name]
                    details = db.list_lot_details()
                    references = db.list_valuation_references()
                    analyses = db.list_ai_analyses()
                    market = db.list_market_references()
                    items = []
                    for lot in lots:
                        item = review_item(lot, details, references, analyses, market)
                        if item["analysis_status"] == "bom_negocio":
                            item["lot_id"] = lot["id"]
                            item["screening_status"] = "potencial"
                            item["group"] = lot["title"]
                            item["known_total"] = (lot.get("current_bid") or lot.get("initial_value") or 0) * (1 + item["detail"]["commission_percent"] / 100) + item["detail"]["fixed_fees"]
                            items.append(item)
                    self.send_json({"items": items, "source": source})
                elif path == "/api/ai/status":
                    self.send_json({"configured": bool(settings.gemini_api_key), "provider": "Gemini", "model": settings.gemini_model, "remaining_today": max(0, settings.ai_daily_limit - db.count_ai_requests_today()), "criteria": db.get_review_criteria() or DEFAULT_CRITERIA})
                elif path == "/api/market/status":
                    self.send_json({"configured": bool(settings.reef_api_key), "source": "Webmotors via ReefAPI"})
                elif path == "/api/filters":
                    self.send_json({"items": db.list_filters()})
                elif path == "/api/opportunities":
                    self.send_json({"items": db.list_opportunities()})
                elif path == "/api/notifications":
                    self.send_json({"items": db.list_notifications()})
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)

            def do_POST(self) -> None:
                path = urlparse(self.path).path
                if path == "/api/fipe/catalog" or re.fullmatch(r"/api/lots/\d+/fipe", path):
                    try:
                        payload = self.read_json()
                        if path == "/api/fipe/catalog":
                            catalog_path = str(payload.get("path") or "")
                            if not re.fullmatch(r"cars/brands(?:/\d+/models(?:/\d+/years)?)?", catalog_path):
                                raise ValueError("Consulta FIPE invalida")
                            rows = cached_fipe(catalog_path, lambda: fipe_client.get(catalog_path))
                            self.send_json({"items": rows})
                        else:
                            lot_id = int(path.split("/")[3])
                            lot = db.get_lot(lot_id)
                            if not lot or not is_car(lot):
                                raise ValueError("Lote indisponivel para consulta FIPE")
                            brand, model, year = (str(payload.get(key) or "") for key in ("brand", "model", "year"))
                            if not re.fullmatch(r"\d+", brand) or not re.fullmatch(r"\d+", model) or not re.fullmatch(r"\d{4}-\d+", year):
                                raise ValueError("Selecione marca, versao e ano")
                            if year.split("-")[0] != str(lot.get("year")):
                                raise ValueError("O ano-modelo deve corresponder ao lote")
                            key = f"vehicle/{brand}/{model}/{year}"
                            result = cached_fipe(key, lambda: fipe_client.vehicle(brand, model, year))
                            db.save_valuation_reference(lot_id, result["value"], result["model"], result["referenceMonth"], result["source_url"])
                            self.send_json({"reference": db.get_valuation_reference(lot_id)})
                    except (ValueError, TypeError) as exc:
                        self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                    return
                if re.fullmatch(r"/api/lots/\d+/market-(search|reference)", path):
                    if not self.authorized():
                        return
                    lot_id = int(path.split("/")[3])
                    lot = db.get_lot(lot_id)
                    if not lot or not is_car(lot):
                        self.send_json({"error": "Consulta disponivel apenas para carros"}, HTTPStatus.BAD_REQUEST)
                        return
                    try:
                        payload = self.read_json()
                        query = market_query(lot, payload)
                        key = query_key(query)
                        if path.endswith("market-reference"):
                            search = db.get_market_cache(key)
                            if not search:
                                raise ValueError("Consulta expirada. Busque os anuncios novamente")
                            result = summarize_market(search, str(payload.get("trim") or ""))
                            db.save_market_reference(lot_id, result)
                            self.send_json({"reference": result})
                        else:
                            if not settings.reef_api_key:
                                raise ValueError("Consulta de mercado nao configurada")
                            with market_lock:
                                search = db.get_market_cache(key)
                                cached = search is not None
                                if search is None:
                                    if not db.reserve_market_request(settings.market_daily_limit):
                                        raise ValueError("Limite diario de consultas de mercado atingido")
                                    search = market_client.search(query)
                                    db.save_market_cache(key, search)
                            summaries = {}
                            for trim in {row["trim"] for row in search["listings"]}:
                                summaries[trim] = {key: value for key, value in summarize_market(search, trim).items() if key != "listings"}
                            self.send_json({"search": search, "summaries": summaries, "cached": cached})
                    except (ValueError, TypeError) as exc:
                        self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                    return
                elif path == "/api/run":
                    if not self.authorized():
                        return
                    stats = service.run_once()
                    self.send_json({"stats": stats})
                elif path == "/api/filters":
                    if not self.authorized():
                        return
                    payload = self.read_json()
                    errors = validate_filter_payload(payload)
                    if errors:
                        self.send_json({"errors": errors}, HTTPStatus.BAD_REQUEST)
                        return
                    filter_id = db.create_filter(
                        payload["name"],
                        payload.get("criteria") or {},
                        payload.get("channels") or ["telegram"],
                        bool(payload.get("active", True)),
                    )
                    self.send_json({"id": filter_id}, HTTPStatus.CREATED)
                elif path == "/api/source":
                    if not self.authorized():
                        return
                    payload = self.read_json()
                    source = payload.get("source")
                    if source not in SOURCES:
                        self.send_json({"error": "site desconhecido"}, HTTPStatus.BAD_REQUEST)
                        return
                    db.select_source(source)
                    self.send_json({"selected": source})
                elif path == "/api/review-criteria":
                    if not self.authorized():
                        return
                    criteria = str(self.read_json().get("criteria") or "").strip()
                    if not 20 <= len(criteria) <= 4000:
                        self.send_json({"error": "Informe criterios entre 20 e 4000 caracteres"}, HTTPStatus.BAD_REQUEST)
                        return
                    db.save_review_criteria(criteria)
                    self.send_json({"ok": True})
                elif re.fullmatch(r"/api/lots/\d+/reference", path):
                    if not self.authorized():
                        return
                    lot_id = int(path.split("/")[3])
                    lot = db.get_lot(lot_id)
                    if not lot or not is_car(lot):
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    payload = self.read_json()
                    try:
                        value = float(payload.get("fipe_value"))
                        label = str(payload.get("model_label") or "").strip()
                        month = str(payload.get("reference_month") or "").strip()
                        url = str(payload.get("source_url") or "").strip()
                        parsed = urlparse(url)
                        if not (1000 <= value <= 10000000 and 5 <= len(label) <= 120 and re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", month)
                                and parsed.scheme == "https" and parsed.hostname in {"www.fipe.org.br", "fipe.org.br", "veiculos.fipe.org.br"}):
                            raise ValueError
                    except (TypeError, ValueError):
                        self.send_json({"error": "Confira valor, versao, mes e link oficial da FIPE"}, HTTPStatus.BAD_REQUEST)
                        return
                    db.save_valuation_reference(lot_id, value, label, month, url)
                    self.send_json({"ok": True})
                elif re.fullmatch(r"/api/lots/\d+/analyze", path):
                    lot_id = int(path.split("/")[3])
                    lot, detail = db.get_lot(lot_id), db.get_lot_detail(lot_id)
                    if not lot or not is_car(lot):
                        self.send_json({"error": "Lote indisponivel para analise"}, HTTPStatus.BAD_REQUEST)
                        return
                    if (not detail or not detail.get("condition_text")) and lot.get("source_site") == "Freitas Leiloeiro":
                        try:
                            info = FreitasScraper().fetch_detail(lot["url"])
                            db.save_lot_detail(lot_id, str(info["classification"]), float(info["commission_percent"]), float(info["fixed_fees"]), str(info["condition_text"]), list(info["image_urls"]), info["notice_url"])
                            detail = db.get_lot_detail(lot_id)
                        except ValueError as exc:
                            logger.exception("Falha na analise do lote %s", lot_id)
                            self.send_json({"error": f"OpenRouter: {exc}"}, HTTPStatus.BAD_GATEWAY)
                            return
                        except Exception:
                            logger.exception("Falha ao obter detalhes do lote %s", lot_id)
                    if not detail or not detail.get("condition_text"):
                        self.send_json({"error": "Nao foi possivel obter as condicoes e taxas do lote"}, HTTPStatus.BAD_REQUEST)
                        return
                    if not settings.gemini_api_key:
                        self.send_json({"error": "IA nao configurada no servidor"}, HTTPStatus.CONFLICT)
                        return
                    fipe_error = None
                    if not db.get_valuation_reference(lot_id):
                        try:
                            result = automatic_fipe(lot)
                            db.save_valuation_reference(lot_id, result["value"], result["model"], result["referenceMonth"], result["source_url"])
                        except ValueError as exc:
                            fipe_error = str(exc)
                    criteria = db.get_review_criteria() or DEFAULT_CRITERIA
                    financial = assess_resale(lot, detail, db.get_valuation_reference(lot_id))
                    financial["market_reference"] = db.list_market_references().get(lot_id)
                    if fipe_error:
                        financial["fipe_status"] = "indisponivel"
                        financial["fipe_note"] = "A FIPE nao respondeu nesta tentativa; a IA nao pode aprovar margem sem referencia valida."
                    evidence = evidence_payload(lot, detail, financial)
                    stamp = fingerprint(criteria, settings.gemini_model, evidence)
                    with ai_lock:
                        cached = db.get_ai_analysis(lot_id)
                        if cached and cached["input_fingerprint"] == stamp:
                            self.send_json({"analysis": cached["result"], "cached": True})
                            return
                        if db.count_ai_requests_today() >= settings.ai_daily_limit:
                            self.send_json({"error": "Limite diario de analises atingido"}, HTTPStatus.TOO_MANY_REQUESTS)
                            return
                        try:
                            report = analyze_with_gemini(criteria, settings.gemini_model, settings.gemini_api_key, evidence)
                        except ValueError as exc:
                            if "fetching image" in str(exc).lower():
                                text_only_evidence = {**evidence, "images": [], "image_note": "Fotos indisponiveis para a IA; avaliar apenas os dados textuais."}
                                try:
                                    report = analyze_with_gemini(criteria, settings.gemini_model, settings.gemini_api_key, text_only_evidence)
                                except ValueError as retry_exc:
                                    exc = retry_exc
                                else:
                                    db.record_ai_request(lot_id, settings.gemini_model)
                                    db.record_ai_analysis(lot_id, settings.gemini_model, stamp, report)
                                    self.send_json({"analysis": report, "cached": False, "images_skipped": True})
                                    return
                            logger.warning("Gemini nao concluiu o lote %s: %s", lot_id, exc)
                            message = str(exc)
                            if "rate-limited" in message.lower() or "rate limit" in message.lower():
                                message = "Os modelos gratuitos estao ocupados agora. Tente novamente em alguns instantes."
                            self.send_json({"error": message}, HTTPStatus.BAD_GATEWAY)
                            return
                        except Exception:
                            logger.exception("Falha na analise do lote %s", lot_id)
                            self.send_json({"error": "Nao foi possivel concluir a analise de IA"}, HTTPStatus.BAD_GATEWAY)
                            return
                        db.record_ai_request(lot_id, settings.gemini_model)
                        db.record_ai_analysis(lot_id, settings.gemini_model, stamp, report)
                    self.send_json({"analysis": report, "cached": False})
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)

            def do_PUT(self) -> None:
                path = urlparse(self.path).path
                if not path.startswith("/api/filters/"):
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                if not self.authorized():
                    return
                filter_id = parse_id(path, "/api/filters/")
                if filter_id is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                payload = self.read_json()
                if "criteria" in payload and not isinstance(payload["criteria"], dict):
                    self.send_json({"errors": ["criteria deve ser objeto"]}, HTTPStatus.BAD_REQUEST)
                    return
                if not db.update_filter(filter_id, payload):
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self.send_json({"ok": True})

            def do_DELETE(self) -> None:
                path = urlparse(self.path).path
                if not path.startswith("/api/filters/"):
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                if not self.authorized():
                    return
                filter_id = parse_id(path, "/api/filters/")
                if filter_id is None or not db.delete_filter(filter_id):
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self.send_json({"ok": True})

            def authorized(self) -> bool:
                expected = f"Bearer {settings.api_token}"
                if self.headers.get("Authorization") != expected:
                    self.send_json({"error": "nao autorizado"}, HTTPStatus.UNAUTHORIZED)
                    return False
                return True

            def read_json(self) -> dict:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0:
                    return {}
                return json.loads(self.rfile.read(length).decode("utf-8"))

            def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def serve_static(self, filename: str, content_type: str) -> None:
                path = Path("web") / filename
                if not path.exists():
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                body = path.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:
                logger.info("%s - %s", self.address_string(), format % args)

        return Handler


def parse_id(path: str, prefix: str) -> int | None:
    value = path.removeprefix(prefix)
    if not value.isdigit():
        return None
    return int(value)


def validate_filter_payload(payload: dict) -> list[str]:
    errors: list[str] = []
    if not payload.get("name"):
        errors.append("name e obrigatorio")
    if not isinstance(payload.get("criteria", {}), dict):
        errors.append("criteria deve ser objeto")
    channels = payload.get("channels", ["telegram"])
    if not isinstance(channels, list) or not all(channel in {"telegram", "email"} for channel in channels):
        errors.append("channels deve conter telegram e/ou email")
    return errors
