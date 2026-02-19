import unittest

try:
    from bs4 import BeautifulSoup
    from src.scrapers.fda_verification_scraper import FDAVerificationScraper
    from src.scrapers.pndf_scraper import PNDFScraper
    SCRAPER_TESTS_AVAILABLE = True
except ImportError:
    SCRAPER_TESTS_AVAILABLE = False


@unittest.skipUnless(SCRAPER_TESTS_AVAILABLE, "BeautifulSoup and scraper modules are required")
class TestFDAScraperHTMLParser(unittest.TestCase):
    def test_parse_results_table_html_with_details(self):
        html = """
        <table class="w-full border-collapse">
          <tbody>
            <tr>
              <td>DR-001</td>
              <td>Paracetamol</td>
              <td>Tylenol</td>
              <td>500 mg</td>
              <td>RX</td>
            </tr>
            <tr class="bg-gray-50">
              <td colspan="6">
                <div class="grid">
                  <div>Manufacturer: ACME Pharma</div>
                  <div>Country / Origin: PH</div>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        """
        matches = FDAVerificationScraper.parse_results_table_html(html)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["registration_number"], "DR-001")
        self.assertEqual(matches[0]["details"]["manufacturer"], "ACME Pharma")
        self.assertEqual(matches[0]["details"]["country___origin"], "PH")

    def test_parse_results_table_html_without_details(self):
        html = """
        <table class="w-full border-collapse">
          <tbody>
            <tr>
              <td>DR-002</td>
              <td>Ibuprofen</td>
              <td>Advil</td>
              <td>200 mg</td>
              <td>OTC</td>
            </tr>
          </tbody>
        </table>
        """
        matches = FDAVerificationScraper.parse_results_table_html(html)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["details"], {})


@unittest.skipUnless(SCRAPER_TESTS_AVAILABLE, "BeautifulSoup and scraper modules are required")
class TestPNDFScraperParser(unittest.TestCase):
    def test_parse_drug_page_includes_found_true(self):
        html = """
        <html><body>
          <h1>Paracetamol</h1>
          <p>ATC Code N02BE01</p>
          <p>Anatomical: Nervous System</p>
          <p>Therapeutic: Analgesics</p>
          <p>Pharmacological: Anilides</p>
          <p>Chemical Class: Acetanilide derivatives</p>
          <h2>Indications</h2>
          <p>Fever and pain.</p>
          <h2>Contraindications</h2>
          <p>Hypersensitivity.</p>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        result = PNDFScraper._parse_drug_page(soup, "paracetamol")
        self.assertIsNotNone(result)
        self.assertTrue(result["found"])
        self.assertEqual(result["name"], "PARACETAMOL")


if __name__ == "__main__":
    unittest.main()
