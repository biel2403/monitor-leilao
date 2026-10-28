import tempfile
import unittest
from pathlib import Path

from auction_monitor.config import Settings
from auction_monitor.database import Database
from auction_monitor.models import RawLot
from auction_monitor.service import MonitorService
from auction_monitor.scrapers.base import AuctionScraper


class StaticScraper(AuctionScraper):
    source_name = "test"

    def fetch_lots(self):
        return [
            RawLot(
                title="Honda Civic 2020",
                url="https://example.com/civic",
                external_id="civic",
                source_site="test",
                category="veiculos",
                brand="Honda",
                year=2020,
                state="SP",
                city="Campinas",
                current_bid=35000,
                reference_value=50000,
            )
        ]


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "test.sqlite3"))
        self.settings = Settings(
            host="127.0.0.1",
            port=0,
            api_token="token",
            database_path=str(Path(self.tmp.name) / "test.sqlite3"),
            scrape_interval_seconds=60,
            scraper_fixture_path="missing.json",
            telegram_bot_token=None,
            telegram_chat_id=None,
            smtp_host=None,
            smtp_port=587,
            smtp_username=None,
            smtp_password=None,
            smtp_from=None,
            smtp_to=None,
            smtp_use_tls=True,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_run_once_records_opportunity_and_avoids_duplicate_notifications(self):
        self.db.migrate()
        self.db.create_filter(
            "Honda SP",
            {"category": "veiculos", "state": "SP", "brands": ["Honda"], "max_price": 40000, "min_discount_percent": 20},
            ["telegram", "email"],
        )
        service = MonitorService(self.settings, self.db, [StaticScraper()])
        first = service.run_once()
        second = service.run_once()

        self.assertEqual(first["new_lots"], 1)
        self.assertEqual(first["opportunities"], 1)
        self.assertEqual(second["new_lots"], 0)
        self.assertEqual(second["opportunities"], 0)
        self.assertEqual(len(self.db.list_notifications()), 2)


if __name__ == "__main__":
    unittest.main()

