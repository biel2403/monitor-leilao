import tempfile
import unittest
from pathlib import Path

from auction_monitor.database import Database
from auction_monitor.market import market_query, normalize_search, summarize_market


class MarketTest(unittest.TestCase):
    def setUp(self):
        self.query = market_query({"year": 2018}, {"make": "Ford", "model": "Ka", "region": "SP"})

    def row(self, identity, price=40000, **extra):
        return {"listing_id": identity, "url": f"https://www.webmotors.com.br/comprar/ford/ka/{identity}",
                "price": price, "year_model": 2018, "make": "FORD", "model": "KA", "trim": "SE 1.0",
                "seller": {"state_code": "SP"}, **extra}

    def test_filters_wrong_year_region_model_and_duplicate(self):
        rows = [self.row(1), self.row(1), self.row(2, year_model=2019), self.row(3, model="FIESTA"),
                self.row(4, seller={"state_code": "RJ"}), self.row(5, has_auction_record=True), self.row(6, float("nan"))]
        search = normalize_search({"data": {"listings": rows}}, self.query)
        self.assertEqual([row["id"] for row in search["listings"]], ["1"])

    def test_separates_versions_and_removes_price_outlier(self):
        rows = [self.row(i, price) for i, price in enumerate([39000, 40000, 41000, 42000, 999999], 1)]
        rows.append(self.row(6, 60000, trim="SE PLUS 1.5"))
        search = normalize_search({"data": {"listings": rows}}, self.query)
        report = summarize_market(search, "SE 1.0")
        self.assertEqual(report["median"], 40500)
        self.assertEqual(report["sample_count"], 4)
        self.assertEqual(report["excluded_count"], 1)

    def test_small_sample_has_no_median(self):
        search = normalize_search({"data": {"listings": [self.row(1), self.row(2)]}}, self.query)
        self.assertIsNone(summarize_market(search, "SE 1.0")["median"])
        with self.assertRaises(ValueError):
            summarize_market(search, "VERSION NOT RETURNED")

    def test_cache_expiry_and_daily_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Database(str(Path(temp) / "test.sqlite3"))
            db.migrate()
            db.save_market_cache("test", {"listings": []})
            self.assertEqual(db.get_market_cache("test"), {"listings": []})
            with db.session() as conn:
                conn.execute("UPDATE market_cache SET collected_at=datetime('now','-2 days')")
            self.assertIsNone(db.get_market_cache("test"))
            self.assertTrue(db.reserve_market_request(1))
            self.assertFalse(db.reserve_market_request(1))
