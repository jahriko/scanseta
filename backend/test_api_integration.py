import asyncio
import importlib.util
import unittest
from unittest.mock import patch


def _deps_available() -> bool:
    required = ["fastapi", "torch", "transformers", "peft", "PIL"]
    return all(importlib.util.find_spec(name) is not None for name in required)


@unittest.skipUnless(_deps_available(), "API integration tests require backend runtime dependencies")
class TestAPIIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main as backend_main

        cls.backend_main = backend_main

    def test_enrich_medications_normalizes_and_dedupes_input(self):
        captured = {}

        async def fake_verify(drug_names):
            captured["verify"] = list(drug_names)
            return [
                {
                    "query": name,
                    "found": False,
                    "matches": [],
                    "best_match": None,
                    "error_code": "mocked",
                    "scraped_at": "2026-01-01T00:00:00",
                }
                for name in drug_names
            ]

        async def fake_enrich(drug_names):
            captured["enrich"] = list(drug_names)
            return [
                {
                    "name": name.upper(),
                    "found": True,
                    "scraped_at": "2026-01-01T00:00:00",
                }
                for name in drug_names
            ]

        request = self.backend_main.EnrichmentRequest(
            drug_names=[" Paracetamol ", "paracetamol", "", "500", "q6h", "Ibuprofen"]
        )

        with patch.object(self.backend_main.FDAVerificationScraper, "verify_medications", side_effect=fake_verify):
            with patch.object(self.backend_main.PNDFScraper, "enrich_medications", side_effect=fake_enrich):
                response = asyncio.run(self.backend_main.enrich_medications(request))

        self.assertEqual(captured["verify"], ["Paracetamol", "Ibuprofen"])
        self.assertEqual(captured["enrich"], ["Paracetamol", "Ibuprofen"])
        self.assertEqual(response.count, 2)


if __name__ == "__main__":
    unittest.main()
