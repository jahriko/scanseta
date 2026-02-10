"""
FDA Verification Portal Web Scraper
Fetches and parses medication information from https://verification.fda.gov.ph/
Uses Playwright to handle JavaScript-rendered React app.
"""

import asyncio
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from .cache_utils import load_cache, normalize_key, save_cache, upsert_cache_entry

logger = logging.getLogger(__name__)

try:
    from playwright.async_api import async_playwright, Browser, Page, TimeoutError as PlaywrightTimeoutError

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("Playwright not installed. Install with: pip install playwright && playwright install chromium")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = PROJECT_ROOT / "data"
CACHE_PATH = CACHE_DIR / "fda_cache.json"
FDA_BASE_URL = "https://verification.fda.gov.ph"

# Set FDA_HEADLESS=false to run browser in visible mode.
FDA_HEADLESS = os.getenv("FDA_HEADLESS", "true").lower() != "false"


class FDAVerificationScraper:
    """Scraper for FDA Verification Portal using Playwright for React app UI."""

    REQUEST_DELAY = 0.5
    CACHE_TTL_SECONDS = int(os.getenv("FDA_CACHE_TTL_SECONDS", "0"))

    _browser: Optional[Browser] = None
    _playwright_context = None

    @staticmethod
    def _cache_key(entry: Dict) -> Optional[str]:
        return entry.get("query")

    @staticmethod
    def _base_result(
        query: str,
        found: bool = False,
        matches: Optional[List[Dict]] = None,
        best_match: Optional[Dict] = None,
        error: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> Dict:
        return {
            "query": query,
            "found": found,
            "matches": matches or [],
            "best_match": best_match,
            "error": error,
            "error_code": error_code,
            "scraped_at": datetime.now().isoformat(),
        }

    @staticmethod
    async def _get_browser() -> Browser:
        """Get or create a shared browser instance with anti-detection settings."""
        if FDAVerificationScraper._browser is None:
            if not PLAYWRIGHT_AVAILABLE:
                raise RuntimeError("Playwright not installed. Run: pip install playwright && playwright install chromium")

            playwright = await async_playwright().start()
            FDAVerificationScraper._playwright_context = playwright

            FDAVerificationScraper._browser = await playwright.chromium.launch(
                headless=FDA_HEADLESS,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )
            if not FDA_HEADLESS:
                logger.info("Running FDA scraper in visible mode (headless=False)")
        return FDAVerificationScraper._browser

    @staticmethod
    async def _close_browser():
        """Close the shared browser instance."""
        if FDAVerificationScraper._browser:
            await FDAVerificationScraper._browser.close()
            FDAVerificationScraper._browser = None
        if FDAVerificationScraper._playwright_context:
            await FDAVerificationScraper._playwright_context.stop()
            FDAVerificationScraper._playwright_context = None

    @staticmethod
    async def search_drug(drug_name: str) -> Dict:
        """Search for a drug on FDA Verification Portal via UI automation."""
        if not PLAYWRIGHT_AVAILABLE:
            logger.error("Playwright not available for FDA scraping")
            return FDAVerificationScraper._base_result(
                query=drug_name,
                error="Playwright not available",
                error_code="playwright_unavailable",
            )

        context = None
        page = None
        try:
            browser = await FDAVerificationScraper._get_browser()
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            )
            page = await context.new_page()
            logger.info(f"Searching FDA for: {drug_name}")

            await page.goto(FDA_BASE_URL, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            search_input = page.locator('input[placeholder*="Type or Press mic icon"]')
            try:
                await search_input.wait_for(state="visible", timeout=10000)
            except PlaywrightTimeoutError:
                return FDAVerificationScraper._base_result(
                    query=drug_name,
                    error="Search input selector not found",
                    error_code="selector_not_found",
                )

            await search_input.fill("")
            await search_input.fill(drug_name)
            await page.wait_for_timeout(500)

            search_button = page.locator('button[title="Search"]')
            if await search_button.is_visible(timeout=2000):
                await search_button.click()
            else:
                await search_input.press("Enter")

            await page.wait_for_timeout(3000)

            table = page.locator("table.w-full.border-collapse")
            if not await table.is_visible(timeout=5000):
                logger.info(f"No results table found for {drug_name}")
                return FDAVerificationScraper._base_result(query=drug_name, found=False)

            matches = await FDAVerificationScraper._parse_results_table(page)
            if not matches:
                return FDAVerificationScraper._base_result(query=drug_name, found=False)

            best_match = FDAVerificationScraper._select_best_match(drug_name, matches)
            return FDAVerificationScraper._base_result(
                query=drug_name,
                found=True,
                matches=matches,
                best_match=best_match,
            )

        except PlaywrightTimeoutError as e:
            logger.error(f"Timeout searching FDA for {drug_name}: {e}")
            return FDAVerificationScraper._base_result(
                query=drug_name,
                error=f"Timeout: {str(e)}",
                error_code="timeout",
            )
        except Exception as e:
            logger.error(f"Error searching FDA for {drug_name}: {e}")
            return FDAVerificationScraper._base_result(
                query=drug_name,
                error=str(e),
                error_code="scrape_error",
            )
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
            if context:
                try:
                    await context.close()
                except Exception:
                    pass

    @staticmethod
    async def _parse_results_table(page: Page) -> List[Dict]:
        """Parse the results table from the FDA portal."""
        matches = []
        try:
            rows = await page.locator("table tbody tr").all()
            for row in rows[:10]:
                row_class = (await row.get_attribute("class") or "").strip()
                if "bg-gray-50" in row_class:
                    continue

                cells = await row.locator("td").all()
                if len(cells) < 5:
                    continue

                registration_number = (await cells[0].inner_text()).strip() if len(cells) > 0 else ""
                generic_name = (await cells[1].inner_text()).strip() if len(cells) > 1 else ""
                brand_name = (await cells[2].inner_text()).strip() if len(cells) > 2 else ""
                dosage_strength = (await cells[3].inner_text()).strip() if len(cells) > 3 else ""
                classification = (await cells[4].inner_text()).strip() if len(cells) > 4 else ""

                details = {}
                details_button = row.locator('button:has-text("View Details")').first
                if await details_button.count() > 0 and await details_button.is_visible(timeout=1000):
                    await details_button.click()
                    await page.wait_for_timeout(300)
                    details = await FDAVerificationScraper._parse_details_for_row(row)

                matches.append(
                    {
                        "registration_number": registration_number,
                        "generic_name": generic_name,
                        "brand_name": brand_name,
                        "dosage_strength": dosage_strength,
                        "classification": classification,
                        "details": details,
                    }
                )
        except Exception as e:
            logger.error(f"Error parsing results table: {e}")

        return matches

    @staticmethod
    async def _parse_details_for_row(row) -> Dict:
        """Parse details from the immediate sibling details row."""
        details_row = row.locator("xpath=following-sibling::tr[1]").first
        if await details_row.count() == 0:
            return {}

        details_class = (await details_row.get_attribute("class") or "").strip()
        if "bg-gray-50" not in details_class:
            return {}

        return await FDAVerificationScraper._parse_details_row(details_row)

    @staticmethod
    async def _parse_details_row(details_row) -> Dict:
        """Parse expanded details row key-value pairs."""
        details = {}
        try:
            detail_divs = await details_row.locator("div.grid div").all()
            for div in detail_divs:
                text = (await div.inner_text()).strip()
                if ":" not in text:
                    continue
                key, value = text.split(":", 1)
                key_normalized = key.strip().lower().replace(" ", "_").replace("/", "_")
                details[key_normalized] = value.strip()
        except Exception as e:
            logger.debug(f"Error parsing details row: {e}")
        return details

    @staticmethod
    def parse_results_table_html(html: str) -> List[Dict]:
        """Fixture-friendly parser for FDA table HTML."""
        soup = BeautifulSoup(html, "lxml")
        rows = soup.select("table tbody tr")
        matches: List[Dict] = []

        i = 0
        while i < len(rows):
            row = rows[i]
            row_classes = " ".join(row.get("class", []))
            if "bg-gray-50" in row_classes:
                i += 1
                continue

            cells = row.find_all("td")
            if len(cells) < 5:
                i += 1
                continue

            details = {}
            if i + 1 < len(rows):
                next_row = rows[i + 1]
                next_classes = " ".join(next_row.get("class", []))
                if "bg-gray-50" in next_classes:
                    details = FDAVerificationScraper._parse_details_html_row(next_row)
                    i += 1

            matches.append(
                {
                    "registration_number": cells[0].get_text(strip=True),
                    "generic_name": cells[1].get_text(strip=True),
                    "brand_name": cells[2].get_text(strip=True),
                    "dosage_strength": cells[3].get_text(strip=True),
                    "classification": cells[4].get_text(strip=True),
                    "details": details,
                }
            )
            i += 1

        return matches

    @staticmethod
    def _parse_details_html_row(details_row) -> Dict:
        details = {}
        for div in details_row.select("div.grid div"):
            text = div.get_text(" ", strip=True)
            if ":" not in text:
                continue
            key, value = text.split(":", 1)
            key_normalized = re.sub(r"\s+", "_", key.strip().lower().replace("/", "_"))
            details[key_normalized] = value.strip()
        return details

    @staticmethod
    def _select_best_match(query: str, matches: List[Dict]) -> Optional[Dict]:
        """Select the best matching result based on query similarity."""
        if not matches:
            return None

        query_lower = query.lower().strip()
        scored_matches = []
        for match in matches:
            score = 0.0
            generic = match.get("generic_name", "").lower()
            brand = match.get("brand_name", "").lower()

            if query_lower == generic or query_lower == brand:
                score = 100.0
            elif query_lower in generic or query_lower in brand:
                score = 80.0
            elif generic.startswith(query_lower) or brand.startswith(query_lower):
                score = 60.0
            else:
                query_words = set(query_lower.split())
                generic_words = set(generic.split())
                brand_words = set(brand.split())
                overlap_generic = len(query_words & generic_words) / max(len(query_words), 1)
                overlap_brand = len(query_words & brand_words) / max(len(query_words), 1)
                score = max(overlap_generic, overlap_brand) * 40.0

            scored_matches.append((score, match))

        scored_matches.sort(key=lambda x: x[0], reverse=True)
        return scored_matches[0][1] if scored_matches else matches[0]

    @staticmethod
    async def load_cache() -> List[Dict]:
        """Load cached FDA data from disk."""
        cache = await load_cache(CACHE_PATH, ttl_seconds=FDAVerificationScraper.CACHE_TTL_SECONDS)
        logger.info(f"Loaded FDA cache with {len(cache)} entries")
        return cache

    @staticmethod
    async def save_cache(data: List[Dict]) -> None:
        """Persist FDA data to disk."""
        saved = await save_cache(
            CACHE_PATH,
            data,
            key_fn=FDAVerificationScraper._cache_key,
            ensure_ascii=False,
        )
        logger.info(f"Saved FDA cache with {len(saved)} entries")

    @staticmethod
    async def verify_medications(drug_names: List[str], cache: Optional[List[Dict]] = None) -> List[Dict]:
        """Verify medications with the FDA portal using cache-first lookups."""
        if cache is None:
            cache = await FDAVerificationScraper.load_cache()

        verified = []
        cache_dict = {
            normalize_key(entry.get("query", "")): entry for entry in cache if normalize_key(entry.get("query", ""))
        }

        for drug_name in drug_names:
            cache_key = normalize_key(drug_name)
            cached_result = cache_dict.get(cache_key)
            if cached_result:
                verified.append(cached_result)
                logger.info(f"Found {drug_name} in FDA cache")
                continue

            logger.info(f"Searching FDA for {drug_name} (not in cache)...")
            result = await FDAVerificationScraper.search_drug(drug_name)
            verified.append(result)

            if normalize_key(result.get("query", "")):
                cache = await upsert_cache_entry(
                    CACHE_PATH,
                    result,
                    key_fn=FDAVerificationScraper._cache_key,
                    ensure_ascii=False,
                )
                cache_dict[cache_key] = result

            await asyncio.sleep(FDAVerificationScraper.REQUEST_DELAY)

        return verified

    @staticmethod
    async def cleanup():
        """Clean up browser resources (call on server shutdown)."""
        await FDAVerificationScraper._close_browser()
        logger.info("FDA scraper cleanup complete")
