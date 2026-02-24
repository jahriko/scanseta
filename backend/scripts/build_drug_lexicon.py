"""
Build a drug lexicon from local PNDF/FDA cache files.

Usage (from backend/):
    python scripts/build_drug_lexicon.py
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set


PLACEHOLDER_VALUES = {
    "",
    "N/A",
    "NA",
    "NONE",
    "NULL",
    "UNKNOWN",
    "UNABLE TO PARSE MEDICATIONS",
}

EXCLUDED_TERMS = {
    "TEST DRUG",
    "TEST BRAND",
}


def _load_json_list(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, dict)]
    except Exception:
        pass
    return []


def _normalize_term(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    # Keep common drug-name separators while cleaning obvious punctuation noise.
    text = re.sub(r"[^A-Za-z0-9\s/\+\-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.upper()

    if text in PLACEHOLDER_VALUES:
        return ""
    if text in EXCLUDED_TERMS:
        return ""
    if len(text) < 2:
        return ""
    if not re.search(r"[A-Z]", text):
        return ""

    return text


def _collect_terms(values: Iterable[Any]) -> Set[str]:
    terms: Set[str] = set()
    for value in values:
        normalized = _normalize_term(value)
        if normalized:
            terms.add(normalized)
    return terms


def _extract_pndf_terms(entries: List[Dict[str, Any]]) -> Set[str]:
    return _collect_terms(entry.get("name") for entry in entries)


def _extract_fda_terms(entries: List[Dict[str, Any]]) -> Set[str]:
    values: List[Any] = []
    for entry in entries:
        values.append(entry.get("query"))

        best_match = entry.get("best_match")
        if isinstance(best_match, dict):
            values.append(best_match.get("generic_name"))
            values.append(best_match.get("brand_name"))

        matches = entry.get("matches")
        if isinstance(matches, list):
            for match in matches:
                if isinstance(match, dict):
                    values.append(match.get("generic_name"))
                    values.append(match.get("brand_name"))

    return _collect_terms(values)


def _load_line_terms(path: Path) -> Set[str]:
    if not path.exists():
        return set()
    values: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        values.append(stripped)
    return _collect_terms(values)


def _write_lexicon(path: Path, terms: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(terms).strip()
    if text:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def build_lexicon(
    pndf_cache: Path,
    fda_cache: Path,
    output: Path,
    include_existing_output: bool,
    overrides_file: Path,
) -> Dict[str, int]:
    pndf_entries = _load_json_list(pndf_cache)
    fda_entries = _load_json_list(fda_cache)

    pndf_terms = _extract_pndf_terms(pndf_entries)
    fda_terms = _extract_fda_terms(fda_entries)
    override_terms = _load_line_terms(overrides_file)
    existing_terms = _load_line_terms(output) if include_existing_output else set()

    merged = sorted(pndf_terms | fda_terms | override_terms | existing_terms)
    _write_lexicon(output, merged)

    return {
        "pndf_terms": len(pndf_terms),
        "fda_terms": len(fda_terms),
        "override_terms": len(override_terms),
        "existing_terms": len(existing_terms),
        "final_terms": len(merged),
    }


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    backend_dir = script_dir.parent
    data_dir = backend_dir / "data"

    parser = argparse.ArgumentParser(description="Build drug_lexicon.txt from PNDF/FDA cache files.")
    parser.add_argument(
        "--pndf-cache",
        default=str(data_dir / "pndf_cache.json"),
        help="Path to PNDF cache JSON file.",
    )
    parser.add_argument(
        "--fda-cache",
        default=str(data_dir / "fda_cache.json"),
        help="Path to FDA cache JSON file.",
    )
    parser.add_argument(
        "--output",
        default=str(data_dir / "drug_lexicon.txt"),
        help="Output path for generated lexicon text file.",
    )
    parser.add_argument(
        "--overrides-file",
        default=str(data_dir / "drug_lexicon_overrides.txt"),
        help="Optional line-delimited extra terms to always include.",
    )
    parser.add_argument(
        "--replace-output",
        action="store_true",
        help="Do not merge existing output contents before writing.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stats = build_lexicon(
        pndf_cache=Path(args.pndf_cache),
        fda_cache=Path(args.fda_cache),
        output=Path(args.output),
        include_existing_output=not args.replace_output,
        overrides_file=Path(args.overrides_file),
    )

    print("Lexicon build complete")
    print(f"- PNDF terms: {stats['pndf_terms']}")
    print(f"- FDA terms: {stats['fda_terms']}")
    print(f"- Overrides terms: {stats['override_terms']}")
    print(f"- Existing terms merged: {stats['existing_terms']}")
    print(f"- Final terms written: {stats['final_terms']}")


if __name__ == "__main__":
    main()
