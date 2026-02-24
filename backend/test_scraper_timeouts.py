import asyncio
import importlib.util
import unittest

if importlib.util.find_spec("bs4") is None:
    FDAVerificationScraper = None  # type: ignore[assignment]
    PNDFScraper = None  # type: ignore[assignment]
else:
    from src.scrapers.fda_verification_scraper import FDAVerificationScraper
    from src.scrapers.pndf_scraper import PNDFScraper


@unittest.skipIf(FDAVerificationScraper is None or PNDFScraper is None, "Scraper dependencies unavailable")
class TestScraperTimeouts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original_fda_search = FDAVerificationScraper.search_drug
        self.original_fda_timeout = FDAVerificationScraper.LOOKUP_TIMEOUT_SECONDS
        self.original_fda_delay = FDAVerificationScraper.REQUEST_DELAY

        self.original_pndf_search = PNDFScraper.search_drug
        self.original_pndf_timeout = PNDFScraper.LOOKUP_TIMEOUT_SECONDS
        self.original_pndf_delay = PNDFScraper.REQUEST_DELAY
        self.original_negative_ttl = PNDFScraper.NEGATIVE_CACHE_TTL_SECONDS

        PNDFScraper._negative_cache.clear()

    async def asyncTearDown(self):
        FDAVerificationScraper.search_drug = staticmethod(self.original_fda_search)  # type: ignore[method-assign]
        FDAVerificationScraper.LOOKUP_TIMEOUT_SECONDS = self.original_fda_timeout
        FDAVerificationScraper.REQUEST_DELAY = self.original_fda_delay

        PNDFScraper.search_drug = staticmethod(self.original_pndf_search)  # type: ignore[method-assign]
        PNDFScraper.LOOKUP_TIMEOUT_SECONDS = self.original_pndf_timeout
        PNDFScraper.REQUEST_DELAY = self.original_pndf_delay
        PNDFScraper.NEGATIVE_CACHE_TTL_SECONDS = self.original_negative_ttl
        PNDFScraper._negative_cache.clear()

    async def test_fda_verify_medications_times_out_fast(self):
        async def slow_search(name: str):
            await asyncio.sleep(1)
            return {"query": name, "found": False}

        FDAVerificationScraper.search_drug = staticmethod(slow_search)  # type: ignore[method-assign]
        FDAVerificationScraper.LOOKUP_TIMEOUT_SECONDS = 0.01
        FDAVerificationScraper.REQUEST_DELAY = 0

        results = await FDAVerificationScraper.verify_medications(["amoxicillin"], cache=[])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].get("error_code"), "timeout")
        self.assertFalse(results[0].get("found"))

    async def test_pndf_enrich_medications_times_out_fast(self):
        async def slow_search(name: str):
            await asyncio.sleep(1)
            return {"name": name.upper(), "found": True}

        PNDFScraper.search_drug = staticmethod(slow_search)  # type: ignore[method-assign]
        PNDFScraper.LOOKUP_TIMEOUT_SECONDS = 0.01
        PNDFScraper.REQUEST_DELAY = 0
        PNDFScraper.NEGATIVE_CACHE_TTL_SECONDS = 60

        results = await PNDFScraper.enrich_medications(["amoxicillin"], cache=[])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].get("error_code"), "timeout")
        self.assertFalse(results[0].get("found"))


if __name__ == "__main__":
    unittest.main()
