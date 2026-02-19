import unittest
from types import SimpleNamespace

from src.post_processing.token_processing import (
    clean_extracted_tokens,
    extract_enrichment_candidates,
    normalize_manual_drug_names,
)


class TestTokenProcessing(unittest.TestCase):
    def test_clean_extracted_tokens_removes_schedule_artifacts(self):
        text = "Paracetamol 500mg q6h PRN, Ibuprofen BID"
        self.assertEqual(clean_extracted_tokens(text), ["Paracetamol", "Ibuprofen"])

    def test_clean_extracted_tokens_splits_connectors(self):
        text = "1) Amoxicillin / Clavulanic Acid and Cetirizine"
        self.assertEqual(
            clean_extracted_tokens(text),
            ["Amoxicillin", "Clavulanic Acid", "Cetirizine"],
        )

    def test_clean_extracted_tokens_parse_error_cases(self):
        self.assertEqual(clean_extracted_tokens(""), [])
        self.assertEqual(clean_extracted_tokens("500mg BID"), [])
        self.assertEqual(clean_extracted_tokens("Unable to parse medications"), [])

    def test_normalize_manual_drug_names(self):
        raw = [" Paracetamol ", "paracetamol", "", "  ", "500", "q6h", "Ibuprofen"]
        self.assertEqual(normalize_manual_drug_names(raw), ["Paracetamol", "Ibuprofen"])

    def test_extract_enrichment_candidates(self):
        meds = [
            SimpleNamespace(name="PARACETAMOL", flags=[]),
            SimpleNamespace(name="Unable to parse medications", flags=["PARSE_ERROR"]),
            SimpleNamespace(name="UNKNOWN", flags=["OOV"]),
            SimpleNamespace(name="ibuprofen", flags=[]),
            SimpleNamespace(name="Ibuprofen", flags=[]),
        ]
        self.assertEqual(extract_enrichment_candidates(meds), ["PARACETAMOL", "ibuprofen"])


if __name__ == "__main__":
    unittest.main()
