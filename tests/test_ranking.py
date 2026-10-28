import unittest
from datetime import datetime

from auction_monitor.ranking import rank_candidates, vehicle_group


def lot(lot_id, title, value, year=2020, closes_at="2026-09-26T10:00:00"):
    return {
        "id": lot_id,
        "title": title,
        "url": f"https://www.freitasleiloeiro.com.br/lot/{lot_id}",
        "source_site": "Freitas Leiloeiro",
        "year": year,
        "current_bid": value,
        "initial_value": None,
        "status": "ABERTO PARA LANCES",
        "closes_at": closes_at,
    }


class RankingTest(unittest.TestCase):
    def test_ranks_only_comparable_open_lots(self):
        lots = [
            lot(1, "VW/GOL 1.0, 19/20", 10000),
            lot(2, "VW/GOL 1.6, 19/20", 20000),
            lot(3, "VW/GOL 1.0, 18/19", 21000, 2019),
            lot(4, "VW/GOL 1.0, 20/21", 22000, 2021),
            lot(5, "VW/GOL 1.0 SUCATA", 1000),
            lot(6, "VW/GOL 1.0", 2000, closes_at="2026-09-20T10:00:00"),
        ]
        ranked = rank_candidates(lots, now=datetime(2026, 9, 24))
        self.assertEqual([item["lot_id"] for item in ranked], [1])
        self.assertEqual(ranked[0]["peer_count"], 3)
        self.assertEqual(ranked[0]["peer_median"], 21000)

    def test_separates_moto_displacement(self):
        self.assertNotEqual(
            vehicle_group(lot(1, "HONDA/CG 125 FAN", 5000)),
            vehicle_group(lot(2, "HONDA/CG 160 FAN", 6000)),
        )

    def test_verified_ranking_includes_fees_and_excludes_insurance(self):
        lots = [
            lot(1, "VW/GOL 1.0, 19/20", 10000),
            lot(2, "VW/GOL 1.6, 19/20", 20000),
            lot(3, "VW/GOL 1.0, 18/19", 21000, 2019),
            lot(4, "VW/GOL 1.0, 20/21", 22000, 2021),
        ]
        details = {1: {"classification": "FINANCEIRA", "commission_percent": 5, "fixed_fees": 2000, "condition_text": "Sem avarias declaradas."}}
        ranked = rank_candidates(lots, now=datetime(2026, 9, 24), details=details, verified_only=True)
        self.assertEqual(ranked[0]["known_total"], 12500)
        self.assertEqual(ranked[0]["below_peers_percent"], 40.5)
        details[1]["classification"] = "SEGURADORA / SINISTRO/MEDIA MONTA"
        self.assertEqual(rank_candidates(lots, now=datetime(2026, 9, 24), details=details, verified_only=True), [])

    def test_declared_structural_damage_is_rejected(self):
        lots = [lot(1, "VW/GOL 1.0", 10000), lot(2, "VW/GOL 1.0", 20000), lot(3, "VW/GOL 1.0", 21000), lot(4, "VW/GOL 1.0", 22000)]
        details = {1: {"classification": "FINANCEIRA", "commission_percent": 5, "fixed_fees": 2000, "condition_text": "DANOS ESTRUTURAIS. VEICULO VENDIDO NO ESTADO."}}
        ranked = rank_candidates(lots, now=datetime(2026, 9, 24), details=details, verified_only=True)
        self.assertEqual(ranked[0]["screening_status"], "descartado")
        self.assertIn("Dano estrutural declarado", ranked[0]["red_flags"])


if __name__ == "__main__":
    unittest.main()
