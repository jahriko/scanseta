"""
Token normalization helpers for OCR output parsing and enrichment gating.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Sequence

PLACEHOLDER_MEDICATION_NAMES = {"unable to parse medications"}
HARD_DISQUALIFYING_FLAGS = {"PARSE_ERROR", "POST_PROCESS_ERROR", "NO_POST_PROCESSOR"}
TRUSTED_STRUCTURED_FLAGS = {"STRUCTURED_JSON", "STRUCTURED_JSON_PARTIAL"}

_DOSAGE_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:mg|ml|mcg|g|tabs?|caps?(?:ules?)?|units?|iu|meq|%)\b",
    flags=re.IGNORECASE,
)
_SCHEDULE_PATTERN = re.compile(
    r"\b(?:bid|tid|qid|daily|once|twice|thrice|od|bd|qd|prn|hs|ac|pc|stat|sos|nocte|qam|qpm|q\d+h)\b",
    flags=re.IGNORECASE,
)
_LEADING_BULLET_PATTERN = re.compile(r"^[\s\-\u2022\*\d\)\.(]+")
_STANDALONE_NUMBERS_PATTERN = re.compile(r"\b\d+\b")
_MULTISPACE_PATTERN = re.compile(r"\s+")
_CONNECTOR_SPLIT_PATTERN = re.compile(r"\s+(?:and|&)\s+", flags=re.IGNORECASE)


def _normalize_candidate_token(text: str) -> str:
    normalized = text.strip()
    normalized = _DOSAGE_PATTERN.sub("", normalized)
    normalized = _LEADING_BULLET_PATTERN.sub("", normalized)
    normalized = _SCHEDULE_PATTERN.sub("", normalized)
    normalized = _STANDALONE_NUMBERS_PATTERN.sub("", normalized)
    return _MULTISPACE_PATTERN.sub(" ", normalized).strip(" -")


def _is_valid_candidate_token(text: str) -> bool:
    if len(text) < 2:
        return False
    if not re.search(r"[A-Za-z]", text):
        return False
    if text.lower() in PLACEHOLDER_MEDICATION_NAMES:
        return False
    return True


def _split_connector_parts(token: str) -> List[str]:
    parts = [part for part in _CONNECTOR_SPLIT_PATTERN.split(token) if part.strip()]
    if len(parts) <= 1:
        return [token]

    normalized_parts = [_normalize_candidate_token(part) for part in parts]
    if all(_is_valid_candidate_token(part) for part in normalized_parts):
        return normalized_parts

    return [token]


def clean_extracted_tokens(text: str) -> List[str]:
    """Parse and normalize OCR output into candidate medication tokens."""
    if not text:
        return []

    cleaned_tokens: List[str] = []

    for raw_token in re.split(r"[,;\n]+", text):
        token = raw_token.strip()
        if not token:
            continue

        normalized_token = _normalize_candidate_token(token)
        if not normalized_token:
            continue

        for part in _split_connector_parts(normalized_token):
            normalized = _normalize_candidate_token(part)
            if not _is_valid_candidate_token(normalized):
                continue

            cleaned_tokens.append(normalized)

    return dedupe_case_insensitive(cleaned_tokens)


def normalize_manual_drug_names(drug_names: Sequence[str], min_length: int = 2) -> List[str]:
    """Normalize manual enrichment requests."""
    normalized: List[str] = []
    for item in drug_names:
        token = _MULTISPACE_PATTERN.sub(" ", str(item or "").strip())
        if len(token) < min_length:
            continue
        if not re.search(r"[A-Za-z]", token):
            continue
        if _SCHEDULE_PATTERN.fullmatch(token):
            continue
        if _DOSAGE_PATTERN.fullmatch(token):
            continue
        if token.lower() in PLACEHOLDER_MEDICATION_NAMES:
            continue
        normalized.append(token)

    return dedupe_case_insensitive(normalized)


def is_enrichment_candidate(name: str, flags: Sequence[str]) -> bool:
    """Return True when a medication entry is safe to send to enrichment scrapers."""
    if not name:
        return False
    if name.strip().lower() in PLACEHOLDER_MEDICATION_NAMES:
        return False

    flag_set = set(flags)
    if any(flag in HARD_DISQUALIFYING_FLAGS for flag in flag_set):
        return False

    if "OOV" in flag_set:
        return False

    is_structured_output = any(flag in TRUSTED_STRUCTURED_FLAGS for flag in flag_set)

    # Keep OCR-token heuristics strict, but trust model-emitted structured fields
    # even when plausibility scoring is conservative.
    if "LOW_PLAUSIBILITY" in flag_set and not is_structured_output:
        return False

    return True


def extract_enrichment_candidates(medications: Iterable[object]) -> List[str]:
    """Collect unique enrichment candidates from parsed MedicationInfo-like objects."""
    candidates: List[str] = []
    for medication in medications:
        name = getattr(medication, "name", "")
        flags = getattr(medication, "flags", []) or []
        if is_enrichment_candidate(name, flags):
            candidates.append(name)

    return dedupe_case_insensitive(candidates)


def dedupe_case_insensitive(values: Iterable[str]) -> List[str]:
    """Deduplicate while preserving first-seen order."""
    seen = set()
    deduped = []
    for value in values:
        key = value.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(value.strip())
    return deduped
