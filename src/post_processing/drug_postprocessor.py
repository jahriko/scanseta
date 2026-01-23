"""
Drug Post-Processor: Candidate matching, plausibility screening, and flagging
Implements:
- Hybrid fuzzy matching (Levenshtein distance + similarity threshold)
- Character-level n-gram language model for plausibility screening
- Token flagging (OOV, LOW_PLAUSIBILITY)
"""

import os
import re
import math
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass
from collections import defaultdict
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


@dataclass
class PostProcessingConfig:
    """Configuration for post-processing"""
    lexicon_path: str = "./data/drug_lexicon.txt"
    max_edit_distance: int = 2
    min_similarity: float = 0.86
    ngram_n: int = 3
    plausibility_threshold: float = -1.0
    max_candidates: int = 10


@dataclass
class MatchResult:
    """Result of matching a token against lexicon"""
    canonical_name: Optional[str]
    original_name: str
    match_method: Optional[str]
    edit_distance: Optional[int]
    similarity: Optional[float]
    plausibility: float
    flags: List[str]


class LexiconLoader:
    """Load and normalize drug lexicon"""
    
    @staticmethod
    def load(lexicon_path: str) -> Tuple[List[str], Dict[str, str]]:
        """
        Load lexicon from file
        Returns: (canonical_forms, normalized_to_canonical)
        """
        path = Path(lexicon_path)
        if not path.exists():
            logger.warning(f"Lexicon file not found: {lexicon_path}")
            return [], {}
        
        canonical_forms = []
        normalized_to_canonical = {}
        
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                canonical = line.strip()
                if not canonical or canonical.startswith('#'):
                    continue
                
                canonical_forms.append(canonical)
                normalized = LexiconLoader.normalize(canonical)
                normalized_to_canonical[normalized] = canonical
        
        logger.info(f"Loaded {len(canonical_forms)} drugs from lexicon")
        return canonical_forms, normalized_to_canonical
    
    @staticmethod
    def normalize(text: str) -> str:
        """Normalize text for matching (lowercase, strip, remove punctuation)"""
        # Lowercase and strip
        normalized = text.lower().strip()
        # Remove non-alphanumeric except spaces
        normalized = re.sub(r'[^a-z0-9\s]', '', normalized)
        # Collapse multiple spaces
        normalized = re.sub(r'\s+', ' ', normalized)
        return normalized.strip()


class CandidateGenerator:
    """Generate candidates using n-gram index and compute fuzzy match scores"""
    
    def __init__(self, canonical_forms: List[str], normalized_to_canonical: Dict[str, str], config: PostProcessingConfig):
        self.canonical_forms = canonical_forms
        self.normalized_to_canonical = normalized_to_canonical
        self.config = config
        
        # Build n-gram inverted index for fast candidate generation
        self.ngram_index = self._build_ngram_index()
    
    def _build_ngram_index(self, n: int = 3) -> Dict[str, Set[str]]:
        """Build inverted index: n-gram -> set of normalized drug names"""
        index = defaultdict(set)
        
        for normalized in self.normalized_to_canonical.keys():
            ngrams = self._extract_ngrams(normalized, n)
            for ngram in ngrams:
                index[ngram].add(normalized)
        
        return dict(index)
    
    @staticmethod
    def _extract_ngrams(text: str, n: int) -> Set[str]:
        """Extract character n-grams from text"""
        if len(text) < n:
            return {text}
        return {text[i:i+n] for i in range(len(text) - n + 1)}
    
    def generate_candidates(self, token: str) -> List[str]:
        """Generate candidate matches using n-gram overlap"""
        normalized_token = LexiconLoader.normalize(token)
        
        # Extract n-grams from token
        token_ngrams = self._extract_ngrams(normalized_token, 3)
        
        # Find candidates with overlapping n-grams
        candidate_scores = defaultdict(int)
        for ngram in token_ngrams:
            if ngram in self.ngram_index:
                for candidate in self.ngram_index[ngram]:
                    candidate_scores[candidate] += 1
        
        # Sort by n-gram overlap and limit
        sorted_candidates = sorted(
            candidate_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )[:self.config.max_candidates]
        
        return [cand for cand, score in sorted_candidates]
    
    def find_best_match(self, token: str) -> Tuple[Optional[str], Optional[str], Optional[int], Optional[float]]:
        """
        Find best match for token
        Returns: (canonical_name, match_method, edit_distance, similarity)
        """
        normalized_token = LexiconLoader.normalize(token)
        
        # Check exact match first
        if normalized_token in self.normalized_to_canonical:
            canonical = self.normalized_to_canonical[normalized_token]
            return canonical, "exact", 0, 1.0
        
        # Generate candidates
        candidates = self.generate_candidates(token)
        
        if not candidates:
            return None, None, None, None
        
        best_canonical = None
        best_method = None
        best_edit_dist = float('inf')
        best_similarity = 0.0
        
        for candidate in candidates:
            # Compute edit distance
            edit_dist = self.levenshtein_distance(normalized_token, candidate)
            
            # Compute similarity
            similarity = SequenceMatcher(None, normalized_token, candidate).ratio()
            
            # Check if meets threshold
            if edit_dist <= self.config.max_edit_distance:
                if edit_dist < best_edit_dist:
                    best_canonical = self.normalized_to_canonical[candidate]
                    best_method = "edit_distance"
                    best_edit_dist = edit_dist
                    best_similarity = similarity
            elif similarity >= self.config.min_similarity:
                if similarity > best_similarity:
                    best_canonical = self.normalized_to_canonical[candidate]
                    best_method = "similarity"
                    best_edit_dist = edit_dist
                    best_similarity = similarity
        
        if best_canonical:
            return best_canonical, best_method, int(best_edit_dist), best_similarity
        
        return None, None, None, None
    
    @staticmethod
    def levenshtein_distance(s1: str, s2: str) -> int:
        """Compute Levenshtein edit distance between two strings"""
        if len(s1) < len(s2):
            return CandidateGenerator.levenshtein_distance(s2, s1)
        
        if len(s2) == 0:
            return len(s1)
        
        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                # Cost of insertions, deletions, substitutions
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
        
        return previous_row[-1]


class PlausibilityModel:
    """Character-level n-gram language model for plausibility scoring"""
    
    def __init__(self, canonical_forms: List[str], config: PostProcessingConfig):
        self.config = config
        self.ngram_counts = defaultdict(int)
        self.context_counts = defaultdict(int)
        self.total_ngrams = 0
        
        # Train on lexicon
        self._train(canonical_forms)
    
    def _train(self, texts: List[str]):
        """Train n-gram model on lexicon"""
        n = self.config.ngram_n
        
        for text in texts:
            # Add boundary markers
            padded = f"^{text.lower()}$"
            
            # Extract n-grams
            for i in range(len(padded) - n + 1):
                ngram = padded[i:i+n]
                context = ngram[:-1]
                
                self.ngram_counts[ngram] += 1
                self.context_counts[context] += 1
                self.total_ngrams += 1
        
        logger.info(f"Trained n-gram model on {len(texts)} drugs, {len(self.ngram_counts)} unique {n}-grams")
    
    def compute_plausibility(self, token: str) -> float:
        """
        Compute log-probability per character
        Higher (less negative) = more plausible
        """
        n = self.config.ngram_n
        padded = f"^{token.lower()}$"
        
        if len(padded) < n:
            return -2.0  # Very implausible for short tokens
        
        log_prob_sum = 0.0
        count = 0
        
        for i in range(len(padded) - n + 1):
            ngram = padded[i:i+n]
            context = ngram[:-1]
            
            # Smoothed probability (add-1 smoothing)
            ngram_count = self.ngram_counts.get(ngram, 0)
            context_count = self.context_counts.get(context, 0)
            vocab_size = len(set(c for ng in self.ngram_counts.keys() for c in ng))
            
            prob = (ngram_count + 1) / (context_count + vocab_size)
            log_prob_sum += math.log(prob)
            count += 1
        
        # Average log-prob per character
        return log_prob_sum / count if count > 0 else -2.0


class Flagger:
    """Assign flags based on matching and plausibility results"""
    
    @staticmethod
    def assign_flags(
        canonical_name: Optional[str],
        plausibility: float,
        plausibility_threshold: float
    ) -> List[str]:
        """Assign flags to token"""
        flags = []
        
        # OOV flag
        if canonical_name is None:
            flags.append("OOV")
        
        # Low plausibility flag
        if plausibility < plausibility_threshold:
            flags.append("LOW_PLAUSIBILITY")
        
        return flags


class DrugPostProcessor:
    """Main post-processor coordinating all components"""
    
    def __init__(self, config: Optional[PostProcessingConfig] = None):
        self.config = config or PostProcessingConfig()
        
        # Load lexicon
        canonical_forms, normalized_to_canonical = LexiconLoader.load(self.config.lexicon_path)
        
        if not canonical_forms:
            logger.warning("Empty lexicon - post-processing will mark all tokens as OOV")
        
        # Initialize components
        self.candidate_generator = CandidateGenerator(
            canonical_forms,
            normalized_to_canonical,
            self.config
        )
        self.plausibility_model = PlausibilityModel(canonical_forms, self.config)
    
    def process_token(self, token: str) -> MatchResult:
        """Process a single token through the pipeline"""
        # Find best match
        canonical, method, edit_dist, similarity = self.candidate_generator.find_best_match(token)
        
        # Compute plausibility
        plausibility = self.plausibility_model.compute_plausibility(token)
        
        # Assign flags
        flags = Flagger.assign_flags(canonical, plausibility, self.config.plausibility_threshold)
        
        return MatchResult(
            canonical_name=canonical,
            original_name=token,
            match_method=method,
            edit_distance=edit_dist,
            similarity=similarity,
            plausibility=plausibility,
            flags=flags
        )
    
    def process_tokens(self, tokens: List[str]) -> List[MatchResult]:
        """Process multiple tokens"""
        results = []
        for token in tokens:
            if token and token.strip():
                result = self.process_token(token.strip())
                results.append(result)
        
        # Log summary
        oov_count = sum(1 for r in results if "OOV" in r.flags)
        low_plaus_count = sum(1 for r in results if "LOW_PLAUSIBILITY" in r.flags)
        
        if results:
            logger.info(
                f"Post-processed {len(results)} tokens: "
                f"{oov_count} OOV, {low_plaus_count} low-plausibility"
            )
        
        return results
