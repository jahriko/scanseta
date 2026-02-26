import re
import unittest
from pathlib import Path


class TestScraperDefaultConfig(unittest.TestCase):
    def _read(self, relative_path: str) -> str:
        root = Path(__file__).resolve().parent
        return (root / relative_path).read_text(encoding="utf-8")

    def _assert_default(self, text: str, variable: str, expected_default: str) -> None:
        pattern = rf'{re.escape(variable)}\s*=\s*[^"\n]*os\.getenv\([^,\n]+,\s*"{re.escape(expected_default)}"\)'
        self.assertRegex(text, pattern)

    def test_enrichment_timeout_defaults(self):
        main_text = self._read("main.py")
        self._assert_default(main_text, "ENRICHMENT_FDA_TIMEOUT_SECONDS", "60")
        self._assert_default(main_text, "ENRICHMENT_PNDF_TIMEOUT_SECONDS", "75")

    def test_fda_scraper_defaults(self):
        fda_text = self._read("src/scrapers/fda_verification_scraper.py")
        self._assert_default(fda_text, "LOOKUP_TIMEOUT_SECONDS", "45")
        self._assert_default(fda_text, "CACHE_TTL_SECONDS", "86400")

    def test_pndf_scraper_defaults(self):
        pndf_text = self._read("src/scrapers/pndf_scraper.py")
        self._assert_default(pndf_text, "LOOKUP_TIMEOUT_SECONDS", "60")
        self._assert_default(pndf_text, "NEGATIVE_CACHE_TTL_SECONDS", "180")


if __name__ == "__main__":
    unittest.main()
