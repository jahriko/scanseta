"""
Token normalization helpers for OCR output parsing and enrichment gating.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Sequence

PLACEHOLDER_MEDICATION_NAMES = {"unable to parse medications"}
DISQUALIFYING_FLAGS = {"PARSE_ERROR", "POST_PROCESS_ERROR", "NO_POST_PROCESSOR", "OOV"}

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
_CONNECTOR_SPLIT_PATTERN = re.compile(r"\s+(?:and|&)\s+|\s*/\s*", flags=re.IGNORECASE)


def clean_extracted_tokens(text: str) -> List[str]:
    """Parse and normalize OCR output into candidate medication tokens."""
    if not text:
        return []

    cleaned_tokens: List[str] = []

    for raw_token in re.split(r"[,;\n]+", text):
        token = raw_token.strip()
        if not token:
            continue

        parts = [part for part in _CONNECTOR_SPLIT_PATTERN.split(token) if part.strip()]
        if not parts:
            parts = [token]

        for part in parts:
            normalized = part.strip()
            normalized = _DOSAGE_PATTERN.sub("", normalized)
            normalized = _LEADING_BULLET_PATTERN.sub("", normalized)
            normalized = _SCHEDULE_PATTERN.sub("", normalized)
            normalized = _STANDALONE_NUMBERS_PATTERN.sub("", normalized)
            normalized = _MULTISPACE_PATTERN.sub(" ", normalized).strip(" -")

            if len(normalized) < 2:
                continue
            if not re.search(r"[A-Za-z]", normalized):
                continue
            if normalized.lower() in PLACEHOLDER_MEDICATION_NAMES:
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
    return not any(flag in DISQUALIFYING_FLAGS for flag in flags)


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
