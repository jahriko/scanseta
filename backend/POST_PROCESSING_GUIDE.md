# Drug Post-Processing Guide

The prescription pipeline no longer treats post-processing as a small fuzzy-match step after OCR. It is now part of a broader parsing and enrichment handoff flow that:

1. normalizes OCR or structured model output into medication candidates,
2. canonicalizes names against the drug lexicon,
3. emits quality and routing flags,
4. decides which medications are safe to enrich, and
5. queues FDA/PNDF enrichment as a background job for the `/scan` flow.

The core goals are still the same:

- correct common OCR typos when the match is clearly safe,
- reject unsafe or ambiguous corrections,
- flag likely garbage tokens,
- keep enrichment away from unreliable medication names.

## Current End-to-End Flow

```text
Model output
  -> parse_model_output()
     -> structured JSON extraction when available
     -> partial structured extraction fallback
     -> legacy token parsing fallback
  -> _build_medication_info()
     -> DrugPostProcessor.process_token()
        -> exact match / conservative fuzzy match
        -> plausibility scoring
        -> flag assignment
  -> extract_enrichment_candidates()
     -> background enrichment job creation for /scan
        -> FDA verification
        -> PNDF enrichment
  -> API response with medication list + enrichment job status
```

## Files

- `backend/src/post_processing/drug_postprocessor.py`
  Main matcher, plausibility scorer, and flagger.
- `backend/src/post_processing/token_processing.py`
  OCR token cleanup, connector splitting, manual drug normalization, and enrichment gating.
- `backend/main.py`
  `MedicationInfo`, parser integration, `/scan`, `/scan-batch`, and enrichment job orchestration.
- `backend/test_post_processing.py`
  Unit tests for matching, abstention, and lexicon availability behavior.
- `backend/test_token_processing.py`
  Tests for token cleanup and enrichment candidate extraction.
- `backend/test_token_processing_enrichment_candidates.py`
  Tests for structured-output enrichment gating behavior.

## MedicationInfo Model

`MedicationInfo` in `backend/main.py` currently includes:

```python
class MedicationInfo(BaseModel):
    name: str
    dosage: Optional[str] = None
    quantity: Optional[str] = None
    signa: Optional[str] = None
    frequency: Optional[str] = None
    confidence: float
    original_name: Optional[str] = None
    flags: List[str] = Field(default_factory=list)
    match_method: Optional[str] = None
    edit_distance: Optional[int] = None
    similarity: Optional[float] = None
    plausibility: Optional[float] = None
```

Notes:

- `name` is the canonical lexicon form when matching succeeds, otherwise the original token.
- `original_name` is populated when the post-processor ran.
- `quantity` and `signa` are now preserved for structured model output.
- `flags` use `default_factory=list`; do not document or reintroduce mutable default lists.

## Parsing Behavior

### Structured Output First

`parse_model_output()` tries to extract a JSON object from the model output before falling back to plain token parsing.

If a valid `medications` list exists, each item is passed through `_build_medication_info()` with:

- `base_flags=["STRUCTURED_JSON"]`
- optional `dosage`
- optional `quantity`
- optional `signa` / `sig`
- optional `frequency`

If only partial structured output can be recovered, medications are tagged with:

- `STRUCTURED_JSON_PARTIAL`

If no structured medications can be recovered, the backend falls back to `parse_prescription_text()`.

### Legacy Token Parsing

`clean_extracted_tokens()` handles raw OCR-style text by:

- splitting on `,`, `;`, and newlines,
- removing dosage artifacts such as `500mg`, `5 ml`, `1 cap`,
- removing schedule/frequency terms such as `BID`, `PRN`, `q6h`, `OD`, `daily`,
- removing standalone numbers and list bullets,
- preserving slash combo drugs such as `Amoxicillin / Clavulanic Acid`,
- splitting `and` / `&` only when both sides still look like valid medication tokens,
- deduplicating tokens case-insensitively while preserving first-seen order.

If parsing yields no usable tokens, the API emits a placeholder medication:

```python
MedicationInfo(
    name="Unable to parse medications",
    confidence=0.0,
    flags=["PARSE_ERROR"],
)
```

## Matching Behavior

### Exact Match

The matcher first normalizes the token with:

- lowercase,
- punctuation removal except spaces,
- whitespace collapsing.

If the normalized token exists in the lexicon, the result is:

- `match_method="exact"`
- `edit_distance=0`
- `similarity=1.0`

### Conservative Fuzzy Match

If exact match fails, `CandidateGenerator`:

1. builds an n-gram inverted index over normalized lexicon entries,
2. shortlists candidates by n-gram overlap,
3. computes Levenshtein edit distance and `SequenceMatcher` similarity,
4. applies extra guards before accepting a correction.

Current acceptance logic is stricter than the original implementation. A candidate must satisfy either:

- edit-distance path:
  `edit_distance <= MAX_EDIT_DISTANCE`
  and `similarity >= MIN_SIMILARITY_FOR_EDIT`
  and `length_delta <= MAX_LENGTH_DELTA`

or:

- similarity path:
  `similarity >= MIN_SIMILARITY`
  and `length_delta <= MAX_LENGTH_DELTA`
  and `normalized_edit <= 0.45`

Candidates are ranked by a blended score favoring similarity first, then lower normalized edit distance, with a small first-character bonus.

### Ambiguity Abstention

The matcher now explicitly abstains when the top two candidates are effectively tied. If two different canonical candidates have scores within `AMBIGUITY_MARGIN`, the post-processor returns no match instead of forcing a correction.

This is important for safety: ambiguous OCR should remain `OOV` rather than silently map to the wrong drug.

## Plausibility Screening

`PlausibilityModel` is a character-level n-gram language model trained from the lexicon at startup.

- Higher plausibility scores are less negative and therefore more drug-like.
- Tokens shorter than the configured n-gram window get a fallback score of `-2.0`.
- Plausibility is used as a fallback signal for unmatched tokens, not as a veto against accepted matches.

That means:

- an accepted exact or fuzzy match keeps its plausibility score for observability,
- but it does not receive `LOW_PLAUSIBILITY`.

If the lexicon cannot be loaded, the backend uses `NullPlausibilityModel`, returns `0.0` plausibility, and adds `LEXICON_UNAVAILABLE`.

## Flags

Current flags relevant to post-processing and routing include:

- `OOV`
  No accepted canonical match was found.
- `LOW_PLAUSIBILITY`
  The token was unmatched and its plausibility score fell below the threshold.
- `LEXICON_UNAVAILABLE`
  The lexicon did not load, so canonicalization cannot succeed.
- `PARSE_ERROR`
  No usable medication tokens were parsed.
- `POST_PROCESS_ERROR`
  The post-processor raised an exception while building medication info.
- `NO_POST_PROCESSOR`
  The post-processor failed to initialize at startup.
- `STRUCTURED_JSON`
  Medication came from fully structured model output.
- `STRUCTURED_JSON_PARTIAL`
  Medication came from partially recovered structured output.

## Enrichment Gating

Enrichment gating now lives in `src/post_processing/token_processing.py`, not in ad hoc endpoint logic.

`is_enrichment_candidate(name, flags)` rejects:

- empty names,
- the placeholder `Unable to parse medications`,
- any medication with `PARSE_ERROR`, `POST_PROCESS_ERROR`, or `NO_POST_PROCESSOR`,
- any medication with `OOV`.

`LOW_PLAUSIBILITY` is treated differently depending on source:

- unstructured OCR token + `LOW_PLAUSIBILITY` => blocked,
- structured model token + `LOW_PLAUSIBILITY` => allowed,
- structured model token + `OOV` => still blocked.

This preserves strict OCR gating without over-penalizing structured model fields.

## `/scan` Flow

The main UI uses `/scan`.

Current behavior:

1. run model inference,
2. parse medications and metadata,
3. run post-processing per medication,
4. collect enrichment-safe drug names,
5. queue an enrichment job if enrichment is enabled and there are valid candidates,
6. return the parsed medication list immediately with job status fields.

Important change: `/scan` no longer waits for FDA/PNDF work to complete before returning a response.

Relevant response fields now include:

- `fda_verification`
- `pndf_enriched`
- `enriched` as a backward-compatible alias for `pndf_enriched`
- `can_enrich`
- `enrichment_job_id`
- `enrichment_status`
- `fda_enrichment_status`
- `pndf_enrichment_status`
- `enrichment_updated_at`
- `enrichment_message`

The returned enrichment arrays may be empty when the job has only been queued.

## `/scan-batch` Flow

`/scan-batch` still uses the same parsing and post-processing stack, but it remains a backend/manual endpoint and does not drive the main frontend UX.

It reports medication parsing results and enrichment eligibility, but it does not mirror the full async job workflow of `/scan`.

## Configuration

Post-processing environment variables are initialized in `backend/main.py`:

```bash
LEXICON_PATH=./data/drug_lexicon.txt
MAX_EDIT_DISTANCE=2
MIN_SIMILARITY=0.86
NGRAM_N=3
PLAUSIBILITY_THRESHOLD=-1.0
MAX_CANDIDATES=10
MAX_LENGTH_DELTA=3
MIN_SIMILARITY_FOR_EDIT=0.75
AMBIGUITY_MARGIN=0.025
```

Operationally relevant enrichment settings nearby include:

```bash
SCAN_RESULT_CACHE_TTL_SECONDS=900
SCAN_RESULT_CACHE_MAX_ENTRIES=64
ENRICHMENT_JOB_TTL_SECONDS=1800
ENRICHMENT_FDA_TIMEOUT_SECONDS=60
ENRICHMENT_PNDF_TIMEOUT_SECONDS=75
ENRICHMENT_MAX_DRUGS=3
ENRICHMENT_PERSIST_DEBOUNCE_SECONDS=0.15
```

## Examples

### Exact Match

```text
Input:  paracetamol
Output: name=PARACETAMOL
Flags:  []
Method: exact
```

### Safe Typo Correction

```text
Input:  paracetmol
Output: name=PARACETAMOL
Flags:  []
Method: edit_distance
```

### Ambiguous OCR Token

```text
Input:  kamillosin
Output: name=kamillosin
Flags:  [OOV]
Method: None
```

### Gibberish Token

```text
Input:  qxztrm
Output: name=qxztrm
Flags:  [OOV, LOW_PLAUSIBILITY]
Method: None
```

### Structured Low-Plausibility Token

```text
Input source: structured JSON
Flags: [STRUCTURED_JSON_PARTIAL, LOW_PLAUSIBILITY]
Enrichment: allowed
```

## Testing

Relevant tests:

```bash
python -m pytest backend/test_post_processing.py
python -m pytest backend/test_token_processing.py
python -m pytest backend/test_token_processing_enrichment_candidates.py
```

Coverage includes:

- exact matching,
- fuzzy matching,
- lexicon normalization,
- ambiguity abstention,
- missing lexicon behavior,
- OCR token cleanup,
- combo-drug preservation,
- connector splitting,
- enrichment candidate extraction,
- structured-output low-plausibility exceptions.

## Observability

The backend logs post-processing and routing summaries including counts for:

- exact matches,
- fuzzy matches,
- `OOV`,
- `LOW_PLAUSIBILITY`,
- blocked-from-enrichment items.

`/scan` also logs queueing and timing information around enrichment-job creation, caching, and response construction.

## Troubleshooting

### All tokens are `OOV`

Check:

- `LEXICON_PATH`
- `backend/data/drug_lexicon.txt`
- startup logs for `LEXICON_UNAVAILABLE`

### Too many false-positive corrections

Tighten:

- `MAX_EDIT_DISTANCE`
- `MIN_SIMILARITY`
- `MIN_SIMILARITY_FOR_EDIT`
- `MAX_LENGTH_DELTA`
- lower `AMBIGUITY_MARGIN` only if abstention is too aggressive

### Too many missed fuzzy matches

Loosen cautiously:

- `MAX_EDIT_DISTANCE`
- `MIN_SIMILARITY`
- `MIN_SIMILARITY_FOR_EDIT`
- `MAX_LENGTH_DELTA`

### Enrichment is unexpectedly skipped

Inspect flags on each `MedicationInfo` entry. The usual blockers are:

- `OOV`
- `PARSE_ERROR`
- `POST_PROCESS_ERROR`
- `NO_POST_PROCESSOR`
- unstructured `LOW_PLAUSIBILITY`

### Post-processor failed to initialize

The API will continue running, but medications will be emitted without canonicalization and may include `NO_POST_PROCESSOR`. Check startup logs and lexicon path configuration first.
