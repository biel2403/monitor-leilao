import tempfile
import unittest
from pathlib import Path

from auction_monitor.database import Database
from auction_monitor.scrapers.freitas import parse_detail, parse_lots


CARD = """
<div class="cardlote">
  <a href="/Leiloes/LoteDetalhes?leilaoId=8069&amp;loteNumero=1">
    <img class="cardLote-img" src="https://cdn3.freitasleiloeiro.com.br/LEILOES/8069/FOTOS/001/LT001_01.JPG">
  </a>
  <div class="cardLote-data"><span>25/09/2026</span><span>10:00</span></div>
  <div class="cardLote-descVeic"><span>RENAULT/KWID ZEN 10MT, 21/22, PRATA</span></div>
  <div class="cardLote-vlr">R$ 31.500,00</div>
  <div class="cardLote-lance">Maior lance</div>
  <span class="cardLote-btn">ABERTO PARA LANCES</span>
</div>
"""


class FreitasTest(unittest.TestCase):
    def test_parses_detail_fees_and_classification(self):
        detail = parse_detail("""
            <div class="text-secondary d-flex flex-column"><span class="fw-bold small">FINANCEIRA</span></div>
            <ul><li><span>5%</span> referente a comissao do leiloeiro</li>
            <li>Despesas operacionais no valor de R$ 2.350,00 por conta do comprador</li>
            <li>Despesas de logistica no valor de R$ 350,00 por conta do comprador</li></ul>
            <div class="text-secondary pt-2 small">DANOS ESTRUTURAIS. VEICULO VENDIDO NO ESTADO.</div>
            <a href="https://cdn3.freitasleiloeiro.com.br/LEILOES/8069/FOTOS/001/LT001_01.JPG">Foto</a>
        """)
        self.assertEqual(detail["classification"], "FINANCEIRA")
        self.assertEqual(detail["commission_percent"], 5)
        self.assertEqual(detail["fixed_fees"], 2700)
        self.assertIn("DANOS ESTRUTURAIS", detail["condition_text"])
        self.assertEqual(len(detail["image_urls"]), 1)

    def test_parses_vehicle_card(self):
        lots = parse_lots(CARD)
        self.assertEqual(len(lots), 1)
        lot = lots[0]
        self.assertEqual(lot.external_id, "8069:1")
        self.assertEqual(lot.current_bid, 31500)
        self.assertEqual(lot.year, 2022)
        self.assertEqual(lot.brand, "RENAULT")
        self.assertEqual(lot.closes_at, "2026-09-25T10:00:00")
        self.assertEqual(lot.source_site, "Freitas Leiloeiro")

    def test_source_selection_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(str(Path(directory) / "monitor.sqlite3"))
            db.migrate()
            self.assertEqual(db.selected_source(), "freitas")
            db.select_source("sample")
            db.migrate()
            self.assertEqual(db.selected_source(), "sample")


if __name__ == "__main__":
    unittest.main()
