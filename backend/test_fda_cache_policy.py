import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

if importlib.util.find_spec("bs4") is None:
    fda_module = None  # type: ignore[assignment]
    FDAVerificationScraper = None  # type: ignore[assignment]
else:
    from src.scrapers import fda_verification_scraper as fda_module
    from src.scrapers.fda_verification_scraper import FDAVerificationScraper


@unittest.skipIf(FDAVerificationScraper is None, "FDA scraper dependencies unavailable")
class TestFDACachePolicy(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_path = Path(self.temp_dir.name) / "fda_cache.json"

        self.original_cache_path = fda_module.CACHE_PATH
        self.original_search_drug = FDAVerificationScraper.search_drug
        self.original_request_delay = FDAVerificationScraper.REQUEST_DELAY
        self.original_lookup_timeout = FDAVerificationScraper.LOOKUP_TIMEOUT_SECONDS

        fda_module.CACHE_PATH = self.cache_path
        FDAVerificationScraper.REQUEST_DELAY = 0
        FDAVerificationScraper.LOOKUP_TIMEOUT_SECONDS = 1

    async def asyncTearDown(self):
        fda_module.CACHE_PATH = self.original_cache_path
        FDAVerificationScraper.search_drug = staticmethod(self.original_search_drug)  # type: ignore[method-assign]
        FDAVerificationScraper.REQUEST_DELAY = self.original_request_delay
        FDAVerificationScraper.LOOKUP_TIMEOUT_SECONDS = self.original_lookup_timeout
        self.temp_dir.cleanup()

    async def test_failed_cached_entry_is_ignored_and_replaced(self):
        stale_failure = [
            {
                "query": "amoxicillin",
                "found": False,
                "matches": [],
                "best_match": None,
                "error": "FDA lookup timed out after 2.0s",
                "error_code": "timeout",
                "scraped_at": "2026-02-25T00:00:00",
            }
        ]
        self.cache_path.write_text(json.dumps(stale_failure), encoding="utf-8")

        calls = 0

        async def fake_search(name: str):
            nonlocal calls
            calls += 1
            return {
                "query": name,
                "found": True,
                "matches": [{"generic_name": "Amoxicillin"}],
                "best_match": {"generic_name": "Amoxicillin"},
                "error": None,
                "error_code": None,
                "scraped_at": "2026-02-25T01:00:00",
            }

        FDAVerificationScraper.search_drug = staticmethod(fake_search)  # type: ignore[method-assign]

        results = await FDAVerificationScraper.verify_medications(["amoxicillin"])
        self.assertEqual(calls, 1)
        self.assertTrue(results[0]["found"])

        persisted = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self.assertEqual(len(persisted), 1)
        self.assertTrue(persisted[0].get("found"))
        self.assertIsNone(persisted[0].get("error_code"))

    async def test_failed_lookup_results_are_not_persisted(self):
        calls = 0

        async def fake_search(name: str):
            nonlocal calls
            calls += 1
            return {
                "query": name,
                "found": False,
                "matches": [],
                "best_match": None,
                "error": "Temporary scraper issue",
                "error_code": "scrape_error",
                "scraped_at": "2026-02-25T01:00:00",
            }

        FDAVerificationScraper.search_drug = staticmethod(fake_search)  # type: ignore[method-assign]

        first = await FDAVerificationScraper.verify_medications(["ibuprofen"], cache=[])
        second = await FDAVerificationScraper.verify_medications(["ibuprofen"], cache=[])

        self.assertEqual(calls, 2)
        self.assertEqual(first[0].get("error_code"), "scrape_error")
        self.assertEqual(second[0].get("error_code"), "scrape_error")
        self.assertFalse(self.cache_path.exists())

    async def test_legacy_not_found_without_error_code_is_ignored_and_replaced(self):
        legacy_entry = [
            {
                "query": "cetirizine",
                "found": False,
                "matches": [],
                "best_match": None,
                "error": None,
                "error_code": None,
                "scraped_at": "2026-02-25T00:00:00",
            }
        ]
        self.cache_path.write_text(json.dumps(legacy_entry), encoding="utf-8")

        calls = 0

        async def fake_search(name: str):
            nonlocal calls
            calls += 1
            return {
                "query": name,
                "found": True,
                "matches": [{"generic_name": "Cetirizine"}],
                "best_match": {"generic_name": "Cetirizine"},
                "error": None,
                "error_code": None,
                "scraped_at": "2026-02-25T01:00:00",
            }

        FDAVerificationScraper.search_drug = staticmethod(fake_search)  # type: ignore[method-assign]

        results = await FDAVerificationScraper.verify_medications(["cetirizine"])
        self.assertEqual(calls, 1)
        self.assertTrue(results[0]["found"])

        persisted = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self.assertEqual(len(persisted), 1)
        self.assertTrue(persisted[0]["found"])


if __name__ == "__main__":
    unittest.main()
