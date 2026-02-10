import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.scrapers.cache_utils import load_cache, save_cache, upsert_cache_entry


class TestCacheUtils(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_path = Path(self.temp_dir.name) / "cache.json"
        self.key_fn = lambda entry: entry.get("query")

    def tearDown(self):
        self.temp_dir.cleanup()

    async def test_save_cache_dedupes_by_key(self):
        entries = [
            {"query": "Paracetamol", "value": 1},
            {"query": "paracetamol", "value": 2},
            {"query": "Ibuprofen", "value": 3},
        ]
        saved = await save_cache(self.cache_path, entries, self.key_fn)
        self.assertEqual(len(saved), 2)
        loaded = await load_cache(self.cache_path)
        self.assertEqual(len(loaded), 2)

    async def test_upsert_cache_entry_concurrent_writes(self):
        async def writer(value: int):
            await upsert_cache_entry(
                self.cache_path,
                {"query": "Paracetamol", "value": value},
                self.key_fn,
            )

        await asyncio.gather(*(writer(i) for i in range(10)))
        loaded = await load_cache(self.cache_path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["query"], "Paracetamol")

    async def test_load_cache_ttl_filters_old_entries(self):
        now = datetime.now(timezone.utc)
        entries = [
            {"query": "fresh", "scraped_at": now.isoformat()},
            {"query": "old", "scraped_at": (now - timedelta(days=3)).isoformat()},
        ]
        await save_cache(self.cache_path, entries, self.key_fn)
        loaded = await load_cache(self.cache_path, ttl_seconds=24 * 3600)
        queries = {entry["query"] for entry in loaded}
        self.assertIn("fresh", queries)
        self.assertNotIn("old", queries)


if __name__ == "__main__":
    unittest.main()
