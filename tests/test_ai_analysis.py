import unittest

from auction_monitor.ai_analysis import build_gemini_request, evidence_payload, fingerprint


class AiAnalysisTest(unittest.TestCase):
    def test_uses_structured_output_without_provider_storage(self):
        evidence = evidence_payload(
            {"title": "VW/NIVUS", "year": 2022, "current_bid": 50000, "images": []},
            {
                "classification": "FINANCEIRA", "commission_percent": 5, "fixed_fees": 2000,
                "condition_text": "Sem observacoes.",
                "image_urls": [
                    "https://cdn3.freitasleiloeiro.com.br/LEILOES/1/FOTOS/car.jpg",
                    "https://example.com/private.jpg",
                ],
            },
        )
        request = build_gemini_request("FIPE -20%", "gemini-2.5-flash", evidence)
        self.assertEqual(request["generationConfig"]["response_mime_type"], "application/json")
        self.assertEqual(request["generationConfig"]["response_schema"]["type"], "OBJECT")
        self.assertIn("required_output_schema", request["contents"][0]["parts"][0]["text"])
        self.assertEqual(len(evidence["images"]), 1)
        self.assertNotEqual(fingerprint("FIPE -20%", "gemini-2.5-flash", evidence), fingerprint("FIPE -30%", "gemini-2.5-flash", evidence))


if __name__ == "__main__":
    unittest.main()
