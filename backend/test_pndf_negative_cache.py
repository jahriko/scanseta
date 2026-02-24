import unittest
from datetime import datetime, timedelta

try:
    from src.scrapers.pndf_scraper import PNDFScraper
except ModuleNotFoundError as exc:
    PNDFScraper = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


@unittest.skipIf(PNDFScraper is None, f"PNDF scraper dependencies unavailable: {_IMPORT_ERROR}")
class TestPNDFNegativeCache(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original_search_drug = PNDFScraper.search_drug
        self.original_negative_ttl = PNDFScraper.NEGATIVE_CACHE_TTL_SECONDS
        PNDFScraper._negative_cache.clear()
        PNDFScraper.NEGATIVE_CACHE_TTL_SECONDS = 60

    async def asyncTearDown(self):
        PNDFScraper.search_drug = staticmethod(self.original_search_drug)  # type: ignore[method-assign]
        PNDFScraper.NEGATIVE_CACHE_TTL_SECONDS = self.original_negative_ttl
        PNDFScraper._negative_cache.clear()

    async def test_recent_miss_short_circuits_repeat_lookup(self):
        calls = 0

        async def fake_search_drug(drug_name: str):
            nonlocal calls
            calls += 1
            return None

        PNDFScraper.search_drug = staticmethod(fake_search_drug)  # type: ignore[method-assign]

        first = await PNDFScraper.enrich_medications(["mysterydrug"], cache=[])
        self.assertEqual(calls, 1)
        self.assertFalse(first[0]["found"])

        second = await PNDFScraper.enrich_medications(["mysterydrug"], cache=[])
        self.assertEqual(calls, 1)
        self.assertEqual(second[0]["error_code"], "recent_miss_cache")

    def test_negative_cache_entry_expires(self):
        PNDFScraper._negative_cache["expired"] = datetime.now() - timedelta(seconds=1)
        self.assertFalse(PNDFScraper._is_negative_cache_hit("expired"))


if __name__ == "__main__":
    unittest.main()
