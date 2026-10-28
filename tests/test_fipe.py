import unittest
from unittest.mock import patch

from auction_monitor.fipe import FipeClient, auction_identity, best_catalog_match


class FipeTest(unittest.TestCase):
    def test_extracts_imported_vehicle_identity(self):
        self.assertEqual(auction_identity("I/VW JETTA CL AF, 19/20, GASOL/ALC"), ("VW VOLKSWAGEN", "JETTA CL AF"))

    def test_selects_closest_catalog_version(self):
        rows = [
            {"code": "1", "label": "Ka 1.0 SE/SE Plus TiVCT Flex 5p"},
            {"code": "2", "label": "Ka 1.5 SE Plus 12V Flex 5p Aut."},
            {"code": "3", "label": "Ka Sedan 1.5 SEL 16V Flex 4p"},
        ]
        matches = best_catalog_match("KA SE 1 0 SD B", rows)
        self.assertEqual(matches[0]["code"], "1")

    def test_expands_common_auction_abbreviations(self):
        rows = [
            {"code": "1", "name": "Jetta Comfortline 1.4 TSI Flex 4p Aut."},
            {"code": "2", "name": "Jetta Trendline 1.4 TSI Flex 4p Aut."},
        ]
        matches = best_catalog_match("JETTA CL AF", rows)
        self.assertEqual(matches[0]["code"], "1")

    def test_parses_price_and_preserves_reference(self):
        payload = {"price": "R$ 40.636,00", "model": "Ka SE", "modelYear": 2018, "referenceMonth": "setembro de 2026", "codeFipe": "003408-8"}
        with patch.object(FipeClient, "get", return_value=payload):
            result = FipeClient().vehicle("22", "6915", "2018-5")
        self.assertEqual(result["value"], 40636)
        self.assertEqual(result["referenceMonth"], "setembro de 2026")

    def test_rejects_different_model_year(self):
        payload = {"price": "R$ 40.636,00", "model": "Ka SE", "modelYear": 2017, "referenceMonth": "setembro de 2026", "codeFipe": "003408-8"}
        with patch.object(FipeClient, "get", return_value=payload), self.assertRaises(ValueError):
            FipeClient().vehicle("22", "6915", "2018-5")

    def test_rejects_paths_outside_vehicle_catalog(self):
        with self.assertRaises(ValueError):
            FipeClient().get("https://example.com")
