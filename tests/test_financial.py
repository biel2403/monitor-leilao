import unittest

from auction_monitor.financial import assess_resale, is_car, max_bid_for_resale


class FinancialTest(unittest.TestCase):
    def test_model_year_threshold_and_fees(self):
        self.assertEqual(max_bid_for_resale(100000, 2019, 5, 2000), {"discount_percent": 30, "max_bid": 64761.90})
        self.assertEqual(max_bid_for_resale(100000, 2020, 5, 2000), {"discount_percent": 20, "max_bid": 74285.71})

    def test_no_fipe_does_not_approve(self):
        lot = {"year": 2022, "current_bid": 40000}
        detail = {"commission_percent": 5, "fixed_fees": 2000}
        self.assertEqual(assess_resale(lot, detail, None)["status"], "sem_fipe")

    def test_motorcycle_excluded(self):
        self.assertFalse(is_car({"title": "HONDA/CG 160 FAN"}))
        self.assertTrue(is_car({"title": "VW/NIVUS HIGHLINE"}))


if __name__ == "__main__":
    unittest.main()
