import tempfile
import unittest
from pathlib import Path

from auction_monitor.database import Database
from auction_monitor.models import RawLot


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "test.sqlite3"))
        self.db.migrate()

    def tearDown(self):
        self.tmp.cleanup()

    def test_upsert_is_idempotent_and_records_changes(self):
        raw = RawLot(
            title="Volkswagen Gol",
            url="https://example.com/1",
            external_id="1",
            source_site="test",
            current_bid=10000,
            bid_count=1,
        )
        lot_id, created, changes = self.db.upsert_lot(raw)
        self.assertTrue(created)
        self.assertEqual(changes, [])

        raw.current_bid = 12000
        raw.bid_count = 2
        second_id, created_again, changes = self.db.upsert_lot(raw)
        self.assertEqual(lot_id, second_id)
        self.assertFalse(created_again)
        self.assertEqual(len(self.db.list_lots()), 1)
        self.assertIn("current_bid", {change["field"] for change in changes})

        with self.db.session() as conn:
            history = conn.execute("SELECT COUNT(*) AS total FROM lot_changes").fetchone()["total"]
            bids = conn.execute("SELECT COUNT(*) AS total FROM bid_history").fetchone()["total"]
        self.assertGreaterEqual(history, 2)
        self.assertEqual(bids, 2)


if __name__ == "__main__":
    unittest.main()
