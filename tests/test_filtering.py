import unittest

from auction_monitor.filtering import calculate_discount_percent, matches_filter


class FilteringTest(unittest.TestCase):
    def test_matches_vehicle_filter(self):
        lot = {
            "category": "veiculos",
            "state": "SP",
            "brand": "Volkswagen",
            "year": 2019,
            "current_bid": 24800,
            "reference_value": 50000,
        }
        criteria = {
            "category": "veiculos",
            "state": "SP",
            "max_price": 40000,
            "min_year": 2018,
            "brands": ["Honda", "Toyota", "Volkswagen"],
            "min_discount_percent": 20,
        }
        matches, labels = matches_filter(lot, criteria)
        self.assertTrue(matches)
        self.assertIn("Preco maximo", labels)
        self.assertIn("Desconto minimo", labels)

    def test_rejects_missing_required_price(self):
        matches, _ = matches_filter({"title": "Lote"}, {"max_price": 1000})
        self.assertFalse(matches)

    def test_brand_choice_matches_imported_vehicle_title(self):
        lot = {"brand": "FORD FOCUS 1.6 FLEX HA, 09", "title": "I/FORD FOCUS 1.6 FLEX HA, 09/09"}
        self.assertTrue(matches_filter(lot, {"brands": ["FORD"]})[0])
        self.assertFalse(matches_filter(lot, {"brands": ["HONDA"]})[0])

    def test_brand_choice_groups_gm_under_chevrolet(self):
        lot = {"brand": "GM", "title": "GM/VECTRA SEDAN ELEGANCE, 10/10"}
        self.assertTrue(matches_filter(lot, {"brands": ["CHEVROLET"]})[0])

    def test_discount(self):
        self.assertEqual(calculate_discount_percent(50000, 35000), 30.0)
        self.assertIsNone(calculate_discount_percent(0, 35000))


if __name__ == "__main__":
    unittest.main()
