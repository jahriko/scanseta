# Drug Post-Processing Implementation Guide

## Overview

This implementation adds three key post-processing techniques to the prescription scanning pipeline:

1. **Candidate Matching** - Hybrid fuzzy matching using Levenshtein edit distance OR similarity threshold
2. **Plausibility Screening** - Character-level n-gram language model for validation
3. **Flagging** - Token-level flags (OOV, LOW_PLAUSIBILITY)

## Architecture

```
VLM Output → Token Parsing → Post-Processing → FDA Verification → PNDF Enrichment → API Response
                                    ↓                    ↓                ↓
                        ┌───────────────────────┐  ┌──────────┐  ┌──────────┐
                        │  DrugPostProcessor    │  │   FDA    │  │   PNDF   │
                        ├───────────────────────┤  │ Scraper  │  │ Scraper  │
                        │ • CandidateGenerator  │  └──────────┘  └──────────┘
                        │   - N-gram indexing   │
                        │   - Levenshtein dist  │
                        │   - Similarity score  │
                        │ • PlausibilityModel   │
                        │   - Char n-gram LM    │
                        │ • Flagger             │
                        │   - OOV detection     │
                        │   - Low plausibility  │
                        └───────────────────────┘
```

## Files Added

1. **data/drug_lexicon.txt** - Static lexicon with 110+ common Philippine drugs
2. **src/post_processing/__init__.py** - Module exports
3. **src/post_processing/drug_postprocessor.py** - Main implementation (400+ lines)
4. **test_post_processing.py** - Core post-processing unit tests (run in CI/local)

## API Changes

### Updated MedicationInfo Model

```python
class MedicationInfo(BaseModel):
    name: str                          # Canonical name (if matched) or original
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    confidence: float
    original_name: Optional[str] = None    # NEW: Raw token from VLM
    flags: List[str] = []                  # NEW: ["OOV", "LOW_PLAUSIBILITY"]
    match_method: Optional[str] = None     # NEW: "exact" | "edit_distance" | "similarity"
    edit_distance: Optional[int] = None    # NEW: Levenshtein distance
    similarity: Optional[float] = None     # NEW: SequenceMatcher ratio
    plausibility: Optional[float] = None   # NEW: N-gram log-prob per char
```

### Example API Response

```json
{
  "success": true,
  "medications": [
    {
      "name": "PARACETAMOL",
      "original_name": "paracetmol",
      "match_method": "edit_distance",
      "edit_distance": 1,
      "similarity": 0.96,
      "plausibility": -0.42,
      "flags": [],
      "confidence": 0.9
    },
    {
      "name": "QXZTRM",
      "original_name": "qxztrm",
      "match_method": null,
      "plausibility": -1.85,
      "flags": ["OOV", "LOW_PLAUSIBILITY"],
      "confidence": 0.9
    }
  ],
  "fda_verification": [...],
  "pndf_enriched": [...],
  "enriched": [...],  // Backward compatibility: same as pndf_enriched
  "can_enrich": true
}
```

## Configuration

Environment variables (with defaults):

```bash
LEXICON_PATH=./data/drug_lexicon.txt
MAX_EDIT_DISTANCE=2
MIN_SIMILARITY=0.86
NGRAM_N=3
PLAUSIBILITY_THRESHOLD=-1.0
MAX_CANDIDATES=10
```

## How It Works

### 1. Token Parsing

The VLM outputs comma-separated drug names. The parser:
- Splits by `,`, `;`, `\n`
- Preserves slash-based combo drugs (for example `Amoxicillin / Clavulanic Acid`)
- Splits `and` / `&` only when the token still looks like a clean medication list after normalization
- Removes dosage units (`mg`, `ml`, `tabs`)
- Removes frequency indicators (`BID`, `TID`, `daily`)
- Cleans whitespace and deduplicates

### 2. Candidate Matching

For each token:
1. **Exact match**: Check normalized form against lexicon
2. **Fuzzy match**: 
   - Generate candidates using trigram overlap (fast shortlisting)
   - Compute Levenshtein distance
   - Compute similarity score (SequenceMatcher)
   - Accept if `edit_distance ≤ MAX_EDIT_DISTANCE` OR `similarity ≥ MIN_SIMILARITY`

### 3. Plausibility Screening

- Train character-level n-gram LM on lexicon
- For each token, compute average log-probability per character
- Flag if below threshold

### 4. Flagging

- **OOV**: No acceptable match found
- **LOW_PLAUSIBILITY**: Token looks unlikely (e.g., random consonants)

### 5. Enrichment

Only tokens that pass enrichment gating are sent to FDA/PNDF enrichment.  
Blocked flags: `OOV`, `PARSE_ERROR`, `POST_PROCESS_ERROR`, `NO_POST_PROCESSOR`.  
Structured model output may bypass `LOW_PLAUSIBILITY`, but not `OOV`.

## Examples

### Exact Match
```
Input:  "paracetamol"
Output: PARACETAMOL (exact, distance=0, similarity=1.0)
Flags:  []
```

### Typo Correction
```
Input:  "paracetmol"  (missing 'a')
Output: PARACETAMOL (edit_distance, distance=1, similarity=0.96)
Flags:  []
```

### OOV Detection
```
Input:  "randomdrug"
Output: randomdrug (no match)
Flags:  ["OOV"]
```

### Low Plausibility
```
Input:  "qxztrm"  (gibberish)
Output: qxztrm
Flags:  ["OOV", "LOW_PLAUSIBILITY"]
Plausibility: -1.85
```

## Testing

Run the test suite:

```bash
python test_post_processing.py
```

**Test Coverage:**
- ✓ Exact matching (case-insensitive)
- ✓ Edit distance matching (1-2 errors)
- ✓ Similarity-based matching
- ✓ OOV flagging
- ✓ Low plausibility flagging
- ✓ Batch processing
- ✓ Whitespace normalization
- ✓ Token cleaning (dosage/frequency removal)
- ✓ Levenshtein distance calculation
- ✓ N-gram extraction

## Performance

- **N-gram indexing**: O(k) candidate generation instead of O(n) full scan
- **MAX_CANDIDATES**: Limits fuzzy matching computation
- **Lazy initialization**: Post-processor loaded at startup
- **Single-token fast path**: Parser calls `process_token()` directly and avoids batch wrapper overhead for one-off tokens

## Observability

Logs include:
- Post-processing summary per request (exact, fuzzy, OOV, low-plausibility, blocked-from-enrichment counts)
- Enrichment statistics (which drugs were enriched)
- Error handling (graceful degradation if post-processor fails)

## Integration Points

1. **main.py**: 
   - Imports and initializes `DrugPostProcessor`
   - Enhanced `parse_prescription_text()` function
   - Updated both `/scan` and `/scan-batch` endpoints
   - Integrates FDA verification (primary) and PNDF enrichment (always)

2. **MedicationInfo**: Extended with 6 new optional fields (backward-compatible)

3. **FDA Verification**: Filtered to skip OOV tokens, verifies against official FDA portal

4. **PNDF Enrichment**: Filtered to skip OOV tokens, always runs as secondary enrichment source

## Future Enhancements

- **Ambiguous match flag**: If top-2 candidates are very close
- **Confidence scoring**: Use fuzzy match quality to adjust confidence
- **Dynamic lexicon**: Load from PNDF cache or database
- **Phonetic matching**: Soundex/Metaphone for pronunciation-based matching
- **Multi-word support**: Handle compound drug names better

## Troubleshooting

**Issue**: All tokens marked as OOV  
**Fix**: Check lexicon file exists at `data/drug_lexicon.txt`

**Issue**: No fuzzy matches  
**Fix**: Adjust `MAX_EDIT_DISTANCE` or `MIN_SIMILARITY` thresholds

**Issue**: Too many false positives  
**Fix**: Decrease `MAX_EDIT_DISTANCE` or increase `MIN_SIMILARITY`

**Issue**: Post-processor not loaded  
**Fix**: Check logs for initialization errors, ensure lexicon file is readable
