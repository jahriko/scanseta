"""
Shared cache helpers for scraper modules.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional


CacheKeyFn = Callable[[dict], Optional[str]]
_LOCKS: Dict[Path, asyncio.Lock] = {}


def normalize_key(value: str) -> str:
    """Normalize cache keys for deterministic matching."""
    if value is None:
        return ""
    normalized = str(value).strip().lower()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _lock_for(path: Path) -> asyncio.Lock:
    resolved = path.resolve()
    if resolved not in _LOCKS:
        _LOCKS[resolved] = asyncio.Lock()
    return _LOCKS[resolved]


def _parse_iso_datetime(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _dedupe_entries(entries: List[dict], key_fn: CacheKeyFn) -> List[dict]:
    deduped: Dict[str, dict] = {}
    passthrough: List[dict] = []
    for entry in entries:
        key = normalize_key(key_fn(entry) or "")
        if not key:
            passthrough.append(entry)
            continue
        deduped[key] = entry
    return [*deduped.values(), *passthrough]


async def load_cache(path: Path, ttl_seconds: Optional[int] = None, timestamp_field: str = "scraped_at") -> List[dict]:
    """Load cache list from disk with optional TTL filtering."""
    lock = _lock_for(path)
    async with lock:
        if not path.exists():
            return []

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                return []
        except Exception:
            return []

        if not ttl_seconds or ttl_seconds <= 0:
            return data

        cutoff = datetime.now(timezone.utc) - timedelta(seconds=ttl_seconds)
        filtered: List[dict] = []
        for entry in data:
            dt = _parse_iso_datetime(str(entry.get(timestamp_field, "")))
            if dt is None or dt >= cutoff:
                filtered.append(entry)
        return filtered


async def save_cache(
    path: Path,
    entries: List[dict],
    key_fn: CacheKeyFn,
    ensure_ascii: bool = False,
) -> List[dict]:
    """Save cache atomically after deduplication."""
    lock = _lock_for(path)
    deduped = _dedupe_entries(entries, key_fn)
    async with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(deduped, f, indent=2, ensure_ascii=ensure_ascii)
        os.replace(temp_path, path)
    return deduped


async def upsert_cache_entry(
    path: Path,
    entry: dict,
    key_fn: CacheKeyFn,
    ensure_ascii: bool = False,
) -> List[dict]:
    """Upsert a single entry atomically and return the updated cache."""
    lock = _lock_for(path)
    async with lock:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                if not isinstance(existing, list):
                    existing = []
            except Exception:
                existing = []
        else:
            existing = []

        merged = _dedupe_entries([*existing, entry], key_fn)

        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=ensure_ascii)
        os.replace(temp_path, path)
        return merged
