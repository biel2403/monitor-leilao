from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from auction_monitor.config import Settings
from auction_monitor.database import Database
from auction_monitor.models import RawLot
from auction_monitor.notifications import build_notifiers, dispatch_notifications, format_opportunity_message
from auction_monitor.opportunities import analyze_lot
from auction_monitor.scrapers import AuctionScraper, FixtureScraper
from auction_monitor.scrapers.freitas import FreitasScraper

logger = logging.getLogger(__name__)


SOURCES = {
    "freitas": {"name": "Freitas Leiloeiro", "url": "https://www.freitasleiloeiro.com.br", "sample": False},
    "sample": {"name": "Dados de exemplo", "url": None, "sample": True},
}


def build_scrapers(settings: Settings, source: str) -> list[AuctionScraper]:
    if source == "freitas":
        return [FreitasScraper()]
    if source == "sample":
        return [FixtureScraper(settings.scraper_fixture_path)]
    raise ValueError(f"Fonte desconhecida: {source}")


class MonitorService:
    def __init__(self, settings: Settings, db: Database, scrapers: list[AuctionScraper] | None = None):
        self.settings = settings
        self.db = db
        self.scrapers = scrapers
        self.notifiers = build_notifiers(settings)

    def run_once(self) -> dict:
        self.db.migrate()
        stats = {
            "scrapers": 0,
            "lots_seen": 0,
            "new_lots": 0,
            "updated_lots": 0,
            "opportunities": 0,
            "notifications": 0,
            "errors": 0,
            "source_errors": [],
            "details_checked": 0,
        }
        for scraper in self.scrapers if self.scrapers is not None else build_scrapers(self.settings, self.db.selected_source()):
            stats["scrapers"] += 1
            try:
                raw_lots = list(scraper.fetch_lots())
                logger.info("Scraper %s retornou %s lotes", scraper.source_name, len(raw_lots))
            except Exception as exc:
                stats["errors"] += 1
                stats["source_errors"].append(f"{scraper.source_name}: {exc}")
                logger.exception("Erro no scraper %s: %s", scraper.source_name, exc)
                continue
            staged_lots: list[tuple[RawLot, int]] = []
            for raw in raw_lots:
                stats["lots_seen"] += 1
                lot_id, created, changes = self.db.upsert_lot(raw)
                if created:
                    stats["new_lots"] += 1
                elif changes:
                    stats["updated_lots"] += 1
                staged_lots.append((raw, lot_id))

            # The list page has the basic lot data, but the final cost and condition live
            # on each detail page. Fetch those pages concurrently so a fresh catalog does
            # not spend several minutes enriching one announcement at a time.
            detail_queue = [
                (raw, lot_id)
                for raw, lot_id in staged_lots
                if scraper.source_name == "Freitas Leiloeiro" and not self.db.get_lot_detail(lot_id)
            ]
            if detail_queue:
                worker_count = min(8, len(detail_queue))
                with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="lot-detail") as executor:
                    futures = {executor.submit(scraper.fetch_detail, raw.url): (raw, lot_id) for raw, lot_id in detail_queue}
                    for future in as_completed(futures):
                        raw, lot_id = futures[future]
                        try:
                            info = future.result()
                            self.db.save_lot_detail(
                                lot_id,
                                str(info["classification"] or ""),
                                float(info["commission_percent"] or 0),
                                float(info["fixed_fees"] or 0),
                                str(info["condition_text"] or ""),
                                list(info["image_urls"] or []),
                                info["notice_url"],
                            )
                            stats["details_checked"] += 1
                        except Exception as exc:
                            logger.warning("Nao foi possivel consultar detalhes do lote %s: %s", lot_id, exc)

            for raw, lot_id in staged_lots:
                opportunities, notifications = self._analyze_lot(lot_id)
                stats["opportunities"] += opportunities
                stats["notifications"] += notifications
        return stats

    def _analyze_lot(self, lot_id: int) -> tuple[int, int]:
        lot = self.db.get_lot(lot_id)
        if lot is None:
            return 0, 0
        count = 0
        notifications = 0
        for filter_row in self.db.list_filters(active_only=True):
            opportunity = analyze_lot(lot, filter_row)
            if opportunity is None:
                continue
            opportunity_id, created = self.db.record_opportunity(
                opportunity["lot_id"],
                opportunity["filter_id"],
                opportunity["matched_criteria"],
                opportunity["discount_percent"],
            )
            if not created:
                continue
            count += 1
            message = format_opportunity_message(opportunity, lot, filter_row["name"])
            notifications += dispatch_notifications(self.db, opportunity_id, filter_row.get("channels") or [], message, self.notifiers)
        return count, notifications

