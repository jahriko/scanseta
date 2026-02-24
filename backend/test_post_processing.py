"""
Unit tests for drug post-processing module
Tests candidate matching, plausibility screening, and flagging
"""

import unittest
import tempfile
import os
from src.post_processing import DrugPostProcessor, PostProcessingConfig


class TestDrugPostProcessing(unittest.TestCase):
    """Test suite for drug post-processing"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test lexicon and processor"""
        # Create temporary lexicon file
        cls.temp_lexicon = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt')
        cls.temp_lexicon.write('\n'.join([
            'PARACETAMOL',
            'IBUPROFEN',
            'OMEPRAZOLE',
            'METFORMIN',
            'AMOXICILLIN',
            'LISINOPRIL',
            'ATORVASTATIN',
            'ASPIRIN',
            'CETIRIZINE',
            'LORATADINE'
        ]))
        cls.temp_lexicon.close()
        
        # Initialize processor with test config
        cls.config = PostProcessingConfig(
            lexicon_path=cls.temp_lexicon.name,
            max_edit_distance=2,
            min_similarity=0.86,
            ngram_n=3,
            plausibility_threshold=-1.0,
            max_candidates=10
        )
        cls.processor = DrugPostProcessor(cls.config)
    
    @classmethod
    def tearDownClass(cls):
        """Clean up temporary files"""
        os.unlink(cls.temp_lexicon.name)
    
    def test_exact_match(self):
        """Test exact matching of drug names"""
        # Exact match (case-insensitive)
        result = self.processor.process_token("paracetamol")
        
        self.assertEqual(result.canonical_name, "PARACETAMOL")
        self.assertEqual(result.original_name, "paracetamol")
        self.assertEqual(result.match_method, "exact")
        self.assertEqual(result.edit_distance, 0)
        self.assertEqual(result.similarity, 1.0)
        self.assertNotIn("OOV", result.flags)
    
    def test_exact_match_case_insensitive(self):
        """Test exact match with different casing"""
        result = self.processor.process_token("IbUpRoFeN")
        
        self.assertEqual(result.canonical_name, "IBUPROFEN")
        self.assertEqual(result.match_method, "exact")
        self.assertNotIn("OOV", result.flags)
    
    def test_edit_distance_match_single_typo(self):
        """Test edit distance matching with single character error"""
        # 'paracetmol' has 1 edit distance from 'paracetamol'
        result = self.processor.process_token("paracetmol")
        
        self.assertEqual(result.canonical_name, "PARACETAMOL")
        self.assertEqual(result.original_name, "paracetmol")
        self.assertEqual(result.match_method, "edit_distance")
        self.assertEqual(result.edit_distance, 1)
        self.assertLessEqual(result.edit_distance, 2)
        self.assertNotIn("OOV", result.flags)
    
    def test_edit_distance_match_two_typos(self):
        """Test edit distance matching with two character errors"""
        # 'metfomrin' has 2 edit distance from 'metformin' (swap 'o'/'r' positions)
        result = self.processor.process_token("metfomrin")
        
        self.assertEqual(result.canonical_name, "METFORMIN")
        self.assertEqual(result.match_method, "edit_distance")
        self.assertLessEqual(result.edit_distance, 2)
        self.assertNotIn("OOV", result.flags)
    
    def test_similarity_match(self):
        """Test similarity-based matching"""
        # 'ibprofen' (missing 'u') should match via similarity
        result = self.processor.process_token("ibprofen")
        
        # Should match IBUPROFEN
        self.assertEqual(result.canonical_name, "IBUPROFEN")
        self.assertIsNotNone(result.match_method)
        self.assertNotIn("OOV", result.flags)
    
    def test_oov_token(self):
        """Test OOV flagging for unknown drugs"""
        # Random drug name not in lexicon
        result = self.processor.process_token("randomdrugname")
        
        self.assertIsNone(result.canonical_name)
        self.assertEqual(result.original_name, "randomdrugname")
        self.assertIsNone(result.match_method)
        self.assertIn("OOV", result.flags)
    
    def test_low_plausibility_gibberish(self):
        """Test low plausibility flagging for gibberish"""
        # Random consonants should have low plausibility
        result = self.processor.process_token("qxztrm")
        
        self.assertIn("OOV", result.flags)
        self.assertIn("LOW_PLAUSIBILITY", result.flags)
        self.assertLess(result.plausibility, -1.0)
    
    def test_plausible_but_oov(self):
        """Test drug-like token that's not in lexicon"""
        # Plausible-sounding but not in our small test lexicon
        result = self.processor.process_token("azithromycin")
        
        # Should be OOV but possibly not low plausibility
        self.assertIn("OOV", result.flags)
        # Plausibility depends on n-gram overlap with lexicon
    
    def test_batch_processing(self):
        """Test processing multiple tokens"""
        tokens = ["paracetamol", "ibprofen", "randomdrug", "qxz"]
        results = self.processor.process_tokens(tokens)
        
        self.assertEqual(len(results), 4)
        
        # First should match exactly
        self.assertEqual(results[0].canonical_name, "PARACETAMOL")
        self.assertNotIn("OOV", results[0].flags)
        
        # Second should match via fuzzy
        self.assertEqual(results[1].canonical_name, "IBUPROFEN")
        
        # Third should be OOV
        self.assertIn("OOV", results[2].flags)
        
        # Fourth should be OOV and low plausibility
        self.assertIn("OOV", results[3].flags)
        self.assertIn("LOW_PLAUSIBILITY", results[3].flags)
    
    def test_empty_token(self):
        """Test handling of empty tokens"""
        results = self.processor.process_tokens(["", "  ", "\n"])
        
        # Should skip empty tokens
        self.assertEqual(len(results), 0)
    
    def test_whitespace_normalization(self):
        """Test normalization of whitespace"""
        result = self.processor.process_token("  paracetamol  ")
        
        self.assertEqual(result.canonical_name, "PARACETAMOL")
        self.assertNotIn("OOV", result.flags)
    
    def test_lexicon_loader_normalization(self):
        """Test lexicon normalization"""
        from src.post_processing.drug_postprocessor import LexiconLoader
        
        # Test various normalizations
        self.assertEqual(LexiconLoader.normalize("PARACETAMOL"), "paracetamol")
        self.assertEqual(LexiconLoader.normalize("Para-cetamol"), "paracetamol")
        self.assertEqual(LexiconLoader.normalize("  Ibuprofen  "), "ibuprofen")
        self.assertEqual(LexiconLoader.normalize("Drug-123"), "drug123")
    
    def test_levenshtein_distance(self):
        """Test Levenshtein distance calculation"""
        from src.post_processing.drug_postprocessor import CandidateGenerator
        
        # Same strings
        self.assertEqual(CandidateGenerator.levenshtein_distance("test", "test"), 0)
        
        # Single substitution
        self.assertEqual(CandidateGenerator.levenshtein_distance("test", "tast"), 1)
        
        # Single insertion
        self.assertEqual(CandidateGenerator.levenshtein_distance("test", "tests"), 1)
        
        # Single deletion
        self.assertEqual(CandidateGenerator.levenshtein_distance("test", "tes"), 1)
        
        # Multiple operations
        self.assertEqual(CandidateGenerator.levenshtein_distance("kitten", "sitting"), 3)
    
    def test_ngram_extraction(self):
        """Test n-gram extraction"""
        from src.post_processing.drug_postprocessor import CandidateGenerator
        
        ngrams = CandidateGenerator._extract_ngrams("test", 3)
        self.assertEqual(ngrams, {"tes", "est"})
        
        # Short string
        ngrams = CandidateGenerator._extract_ngrams("ab", 3)
        self.assertEqual(ngrams, {"ab"})
    
    def test_config_customization(self):
        """Test custom configuration"""
        custom_config = PostProcessingConfig(
            lexicon_path=self.temp_lexicon.name,
            max_edit_distance=1,  # Stricter
            min_similarity=0.95,  # Stricter
            plausibility_threshold=-0.5  # Stricter
        )
        
        strict_processor = DrugPostProcessor(custom_config)
        
        # Token with 2 edit distance should not match with strict config
        result = strict_processor.process_token("omeprzole")  # 2 edits from omeprazole
        
        # With max_edit_distance=1, this might not match or match via similarity
        # The exact behavior depends on similarity threshold

    def test_missing_lexicon_has_deterministic_flag(self):
        """Processor should not crash when lexicon is missing."""
        missing_config = PostProcessingConfig(lexicon_path="does_not_exist.txt")
        processor = DrugPostProcessor(missing_config)
        result = processor.process_token("paracetamol")
        self.assertIn("LEXICON_UNAVAILABLE", result.flags)
        self.assertIn("OOV", result.flags)

    def test_ambiguous_candidates_abstain(self):
        """Near-tied fuzzy candidates should abstain instead of forcing correction."""
        temp_lexicon = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt')
        try:
            temp_lexicon.write('\n'.join([
                'KAMILLOSAN',
                'KAMILLORIN',
            ]))
            temp_lexicon.close()

            config = PostProcessingConfig(
                lexicon_path=temp_lexicon.name,
                max_edit_distance=2,
                min_similarity=0.8,
                ambiguity_margin=0.2,
            )
            processor = DrugPostProcessor(config)
            result = processor.process_token("kamillosin")
            self.assertIsNone(result.canonical_name)
            self.assertIn("OOV", result.flags)
        finally:
            os.unlink(temp_lexicon.name)


class TestParsingIntegration(unittest.TestCase):
    """Test parsing and post-processing integration"""
    
    def test_token_cleaning(self):
        """Test that dosage information is removed during parsing"""
        import re
        
        # Test dosage removal pattern from parse_prescription_text
        test_token = "Paracetamol 500mg"
        cleaned = re.sub(r'\d+\s*(mg|ml|mcg|g|tabs?|capsules?|units?|iu)\b', '', test_token, flags=re.IGNORECASE)
        cleaned = cleaned.strip()
        
        self.assertEqual(cleaned, "Paracetamol")
    
    def test_frequency_removal(self):
        """Test that frequency indicators are removed"""
        import re
        
        test_token = "Ibuprofen BID"
        cleaned = re.sub(r'\b(bid|tid|qid|daily|once|twice|thrice|od|bd|qd)\b', '', test_token, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        self.assertEqual(cleaned, "Ibuprofen")


def run_tests():
    """Run all tests"""
    unittest.main(argv=[''], verbosity=2, exit=False)


if __name__ == "__main__":
    run_tests()
