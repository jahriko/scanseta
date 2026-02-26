import unittest

from src.post_processing.token_processing import extract_enrichment_candidates, is_enrichment_candidate


class _MedicationStub:
    def __init__(self, name: str, flags):
        self.name = name
        self.flags = flags


class TestTokenProcessingEnrichmentCandidates(unittest.TestCase):
    def test_structured_partial_with_low_plausibility_is_allowed(self):
        self.assertTrue(
            is_enrichment_candidate(
                "celecoxib",
                ["STRUCTURED_JSON_PARTIAL", "LOW_PLAUSIBILITY"],
            )
        )

    def test_unstructured_low_plausibility_is_rejected(self):
        self.assertFalse(is_enrichment_candidate("celecoxib", ["LOW_PLAUSIBILITY"]))

    def test_hard_disqualifier_still_rejected_for_structured_output(self):
        self.assertFalse(
            is_enrichment_candidate(
                "celecoxib",
                ["STRUCTURED_JSON_PARTIAL", "PARSE_ERROR"],
            )
        )

    def test_extract_candidates_keeps_structured_partial_entries(self):
        medications = [
            _MedicationStub("CELECOXIB", ["STRUCTURED_JSON_PARTIAL", "LOW_PLAUSIBILITY"]),
            _MedicationStub("AMLODIPINE", ["STRUCTURED_JSON", "LOW_PLAUSIBILITY"]),
            _MedicationStub("garbage-token", ["LOW_PLAUSIBILITY"]),
        ]
        self.assertEqual(extract_enrichment_candidates(medications), ["CELECOXIB", "AMLODIPINE"])


if __name__ == "__main__":
    unittest.main()
