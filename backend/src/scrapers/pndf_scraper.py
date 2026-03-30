"""
Philippine National Drug Formulary (PNDF) Web Scraper
Fetches and parses medication information from https://pnf.doh.gov.ph/

Uses patchright (anti-detection Playwright fork) with headless=False to bypass
Cloudflare WAF. The browser window is positioned off-screen so it is invisible
to the user while still passing CF's bot-detection checks.
"""

import asyncio
import json
import logging
import os
<<<<<<< HEAD
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

=======
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import re
>>>>>>> d051e7d6b3726db590b9f026cd179df9d0975181
from .cache_utils import load_cache, normalize_key, save_cache, upsert_cache_entry

logger = logging.getLogger(__name__)

try:
    from patchright.sync_api import sync_playwright
    PATCHRIGHT_AVAILABLE = True
except ImportError:
    PATCHRIGHT_AVAILABLE = False
    logger.warning(
        "patchright not installed. Install with: pip install patchright && patchright install chromium"
    )

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = PROJECT_ROOT / "data"
CACHE_PATH = CACHE_DIR / "pndf_cache.json"
FRONTEND_URL = "https://pnf.doh.gov.ph/"
TIMEOUT = 60_000


# ---------------------------------------------------------------------------
# Core sync scraper (runs in a thread pool to keep the async API intact)
# ---------------------------------------------------------------------------

def _scrape_drug_sync(drug_name: str) -> List[Dict]:
    """
    Synchronous core: launches patchright Chromium off-screen, performs the
    search, expands each accordion result, and returns a list of raw dicts.

    Each dict has: id (str|None), name (str), details (dict[str,str]).
    """
    search_data: dict = {"body": None}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--window-position=-10000,-10000"],
        )
        page = browser.new_page(viewport={"width": 1280, "height": 800})

        def on_response(response):
            if (
                "pnf-api.doh.gov.ph/api/home" in response.url
                and "globalSearch=" in response.url
            ):
                term = urllib.parse.unquote(
                    response.url.split("globalSearch=")[-1].split("&")[0]
                )
                if term.lower() == drug_name.lower():
                    try:
                        search_data["body"] = json.loads(response.body())
                        logger.debug(f"[pndf] Got search results for '{term}'")
                    except Exception as exc:
                        logger.warning(f"[pndf] Response parse error: {exc}")

        page.on("response", on_response)

        try:
            logger.info(f"[pndf] Loading {FRONTEND_URL} …")
            page.goto(FRONTEND_URL, wait_until="networkidle", timeout=TIMEOUT)
            logger.info(f"[pndf] Page loaded: {page.title()}")

            # --- Dismiss disclaimer modal ---
            try:
                page.wait_for_selector(
                    "div[role='dialog'][data-state='open']",
                    state="visible",
                    timeout=8_000,
                )
                close_btn = page.locator("button[data-slot='close-button']")
                if close_btn.count() and close_btn.is_visible():
                    close_btn.first.click()
                else:
                    page.keyboard.press("Escape")
                page.wait_for_selector(
                    "div[data-slot='dialog-overlay']",
                    state="hidden",
                    timeout=8_000,
                )
                logger.debug("[pndf] Modal dismissed.")
            except Exception:
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)

            # --- Type drug name (keyboard.type triggers React's debounced search) ---
            logger.info(f"[pndf] Searching for '{drug_name}' …")
            search_input = page.locator("#inputGlobalSearch")
            search_input.wait_for(state="visible", timeout=10_000)
            search_input.click()
            page.keyboard.type(drug_name, delay=100)

            # --- Poll for API response ---
            logger.info("[pndf] Waiting for API response …")
            for _ in range(20):
                page.wait_for_timeout(1_000)
                if search_data["body"] is not None:
                    break

            if search_data["body"] is None:
                logger.warning(f"[pndf] No search response received for '{drug_name}'.")
                return []

            drug_ids = _extract_drug_list(search_data["body"])
            logger.info(f"[pndf] {len(drug_ids)} result(s) found.")
            if not drug_ids:
                return []

            # --- Wait for result cards ---
            try:
                page.wait_for_selector(
                    "div.w-full.group > button",
                    state="visible",
                    timeout=30_000,
                )
            except Exception:
                logger.warning("[pndf] Result buttons not found. Returning IDs only.")
                return drug_ids

            # --- Wait for sync spinner to finish ---
            try:
                page.wait_for_selector(
                    "text=Syncing pharmacopoeia data",
                    state="hidden",
                    timeout=60_000,
                )
            except Exception:
                pass

            # --- Expand each accordion item ---
            results = []
            item_groups = page.locator("div.w-full.group")
            count = item_groups.count()
            logger.info(f"[pndf] Expanding {count} item(s) …")

            for i in range(count):
                group = item_groups.nth(i)
                btn = group.locator("button").first
                drug_name_text = btn.locator("h3").inner_text().strip()

                btn.click()
                detail_selector = "div.px-4.py-4"
                try:
                    group.locator(detail_selector).wait_for(
                        state="visible", timeout=15_000
                    )
                except Exception:
                    page.wait_for_timeout(2_000)

                detail_el = group.locator(detail_selector)
                if detail_el.count() > 0:
                    panel_text = detail_el.first.inner_text().strip()
                else:
                    panel_text = group.inner_text().strip()
                    if panel_text.startswith(drug_name_text):
                        panel_text = panel_text[len(drug_name_text):].strip()

                entry = _parse_panel(drug_name_text, panel_text)
                if i < len(drug_ids):
                    entry["id"] = drug_ids[i].get("id")

                results.append(entry)

                btn.click()
                page.wait_for_timeout(300)

            return results

        finally:
            browser.close()


def _extract_drug_list(body) -> List[Dict]:
    if isinstance(body, list):
        for item in body:
            if isinstance(item, dict) and "drugGenerics" in item:
                return item["drugGenerics"]
    if isinstance(body, dict):
        return body.get("drugGenerics", [])
    return []


def _parse_panel(name: str, panel: str) -> Dict:
    """Parse the accordion detail panel text into a flat key→value dict."""
    result: Dict = {"name": name, "details": {}}
    if not panel:
        return result

    lines = [line.strip() for line in panel.splitlines() if line.strip()]
    current_key = None
    current_vals: List[str] = []

    for line in lines:
        if ":" in line and len(line.split(":")[0]) < 60:
            if current_key:
                result["details"][current_key] = " ".join(current_vals).strip()
            parts = line.split(":", 1)
            current_key = parts[0].strip()
            current_vals = [parts[1].strip()] if len(parts) > 1 and parts[1].strip() else []
        else:
            if current_key:
                current_vals.append(line)

    if current_key:
        result["details"][current_key] = " ".join(current_vals).strip()

    if not result["details"]:
        result["raw"] = panel

    return result


def _details_to_enrichment(raw: Dict) -> Dict:
    """
    Convert the raw scrape result (name + details flat dict) into the
    structured dict expected by PNDFEnrichmentItem in main.py.
    """
    details: Dict = raw.get("details", {})

    def get(*keys: str) -> Optional[str]:
        for k in keys:
            for dk, dv in details.items():
                if dk.strip().lower() == k.lower() and dv:
                    return dv
        return None

    # Dosage forms: plain text value split into list items
    raw_dosage = get("Dosage Form(s)", "Dosage Forms", "Dosage Form")
    dosage_forms = []
    if raw_dosage:
        for part in raw_dosage.split(","):
            part = part.strip()
            if part:
                dosage_forms.append({"form": part})

    # ATC code: may appear as "ATC Code" key or embedded value like "R03AC02"
    atc_raw = get("ATC Code", "ATC")
    atc_code = None
    if atc_raw:
        import re
        m = re.search(r"[A-Z]\d{2}[A-Z]{2}\d{2}", atc_raw)
        atc_code = m.group(0) if m else atc_raw.strip()

    classification = {
        "anatomical": get("Anatomical"),
        "therapeutic": get("Therapeutic"),
        "pharmacological": get("Pharmacological"),
        "chemical_class": get("Chemical Class"),
    }
    # Omit classification block if all fields are empty
    if not any(classification.values()):
        classification = None

    return {
        "name": raw.get("name", ""),
        "found": True,
        "atc_code": atc_code,
        "classification": classification,
        "dosage_forms": dosage_forms,
        "indications": get("Indications", "Indication"),
        "contraindications": get("Contraindications", "Contraindication"),
        "precautions": get("Precautions", "Precaution"),
        "adverse_reactions": get(
            "Adverse Drug Reactions", "Adverse Reactions", "Adverse Effects"
        ),
        "drug_interactions": get("Drug Interactions", "Drug Interaction"),
        "mechanism_of_action": get("Mechanism of Action", "Mechanism"),
        "dosage_instructions": get("Dosage", "Dosage Instructions", "Dosing"),
        "administration": get("Administration", "Route of Administration"),
        "pregnancy_category": get("Pregnancy Category", "Pregnancy"),
        "scraped_at": datetime.now().isoformat(),
    }


# ---------------------------------------------------------------------------
# PNDFScraper — async public API (same interface as the original class)
# ---------------------------------------------------------------------------

class PNDFScraper:
    """
    Async scraper for the Philippine National Drug Formulary.

    Internally runs patchright in a thread pool so the blocking browser
    interaction doesn't block the FastAPI event loop.
    """

<<<<<<< HEAD
    REQUEST_DELAY = 0.5
    CACHE_TTL_SECONDS = int(os.getenv("PNDF_CACHE_TTL_SECONDS", "0"))
=======
    # Request delay (seconds) between searches to respect server
    REQUEST_DELAY = float(os.getenv("PNDF_REQUEST_DELAY_SECONDS", "0.1"))
    LOOKUP_CONCURRENCY = max(1, int(os.getenv("PNDF_LOOKUP_CONCURRENCY", "2")))
    LOOKUP_TIMEOUT_SECONDS = float(os.getenv("PNDF_LOOKUP_TIMEOUT_SECONDS", "60"))
    CACHE_TTL_SECONDS = int(os.getenv("PNDF_CACHE_TTL_SECONDS", "0"))
    NEGATIVE_CACHE_TTL_SECONDS = int(os.getenv("PNDF_NEGATIVE_CACHE_TTL_SECONDS", "180"))
    
    # Shared browser instance (initialized lazily)
    _browser: Optional[Browser] = None
    _playwright_context = None
    _negative_cache: Dict[str, datetime] = {}

    @staticmethod
    def _error_result(
        drug_name: str,
        *,
        error: str,
        error_code: str,
        message: Optional[str] = None,
    ) -> Dict:
        return {
            "name": drug_name,
            "found": False,
            "message": message or error,
            "error": error,
            "error_code": error_code,
            "scraped_at": datetime.now().isoformat(),
        }
>>>>>>> d051e7d6b3726db590b9f026cd179df9d0975181

    @staticmethod
    def _cache_key(entry: Dict) -> Optional[str]:
        return entry.get("name")

    @staticmethod
<<<<<<< HEAD
    async def search_drug(drug_name: str) -> Optional[Dict]:
        """
        Search for a single drug name on pnf.doh.gov.ph.
=======
    def _safe_filename(value: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", value.strip())
        return safe.strip("._") or "query"

    @staticmethod
    def _purge_negative_cache() -> None:
        if not PNDFScraper._negative_cache:
            return

        now = datetime.now()
        expired_keys = [key for key, expiry in PNDFScraper._negative_cache.items() if expiry <= now]
        for key in expired_keys:
            PNDFScraper._negative_cache.pop(key, None)

    @staticmethod
    def _is_negative_cache_hit(cache_key: str) -> bool:
        if not cache_key or PNDFScraper.NEGATIVE_CACHE_TTL_SECONDS <= 0:
            return False
        PNDFScraper._purge_negative_cache()
        expiry = PNDFScraper._negative_cache.get(cache_key)
        return bool(expiry and expiry > datetime.now())

    @staticmethod
    def _remember_negative_lookup(cache_key: str) -> None:
        if not cache_key or PNDFScraper.NEGATIVE_CACHE_TTL_SECONDS <= 0:
            return
        PNDFScraper._negative_cache[cache_key] = datetime.now() + timedelta(
            seconds=PNDFScraper.NEGATIVE_CACHE_TTL_SECONDS
        )

    @staticmethod
    async def _get_browser() -> Browser:
        """Get or create a shared browser instance with anti-detection settings"""
        if PNDFScraper._browser is None:
            if not PLAYWRIGHT_AVAILABLE:
                raise RuntimeError("Playwright not installed. Run: pip install playwright && playwright install chromium")
            
            playwright = await async_playwright().start()
            PNDFScraper._playwright_context = playwright
            
            # Launch browser with stealth settings to avoid Cloudflare detection
            # Note: Cloudflare detects headless browsers easily, so headless=False is recommended
            # Set PNDF_HEADLESS=false environment variable to run in visible mode
            PNDFScraper._browser = await playwright.chromium.launch(
                headless=PNDF_HEADLESS,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-blink-features=AutomationControlled',  # Hide automation
                    '--disable-dev-shm-usage',
                ]
            )
            if not PNDF_HEADLESS:
                logger.info("Running in visible mode (headless=False) to bypass Cloudflare detection")
        return PNDFScraper._browser

    @staticmethod
    async def _close_browser():
        """Close the shared browser instance"""
        if PNDFScraper._browser:
            await PNDFScraper._browser.close()
            PNDFScraper._browser = None
        if PNDFScraper._playwright_context:
            await PNDFScraper._playwright_context.stop()
            PNDFScraper._playwright_context = None

    @staticmethod
    async def _handle_radix_dialog(page: Page) -> None:
        """
        Handle Disclaimer Modal (Radix dialog) that appears on page refresh.
        The modal blocks the page, so it must be closed before interacting with elements.
        """
        try:
            await page.wait_for_timeout(1000)

            def open_dialog_locator():
                return page.locator('[role="dialog"]:visible, [id^="radix-"][data-state="open"]')

            if await open_dialog_locator().count() == 0:
                logger.debug("No open disclaimer dialog detected")
                return

            logger.info("Open disclaimer dialog detected; closing it before search")

            close_selectors = [
                '[role="dialog"] button[aria-label="Close"]',
                '[role="dialog"] [data-radix-dialog-close]',
                '[role="dialog"] button:has-text("Close")',
                'button[aria-label="Close"]',
                'button[data-radix-dialog-close]',
                'button:has-text("Close")',
            ]

            for selector in close_selectors:
                close_buttons = page.locator(selector)
                count = await close_buttons.count()
                if count == 0:
                    continue

                for idx in range(count):
                    close_button = close_buttons.nth(idx)
                    try:
                        if not await close_button.is_visible():
                            continue
                        await close_button.click(timeout=2000)
                        await page.wait_for_timeout(400)
                        if await open_dialog_locator().count() == 0:
                            logger.info("Disclaimer dialog closed successfully")
                            return
                    except Exception as click_error:
                        logger.debug(f"Failed clicking close selector {selector}: {click_error}")
                        continue

            logger.info("Falling back to Escape key for dialog close")
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(400)

            if await open_dialog_locator().count() == 0:
                logger.info("Disclaimer dialog closed via Escape")
            else:
                logger.warning("Disclaimer dialog still appears open; interactions may fail")
        except Exception as e:
            logger.debug(f"Error handling dialog (may not exist): {e}")

    @staticmethod
    async def _find_disclosure_button(page: Page, drug_name: str):
        """
        Find the best matching visible accordion button for a drug result.
        """
        query = drug_name.strip().upper()
        if not query:
            return None

        pattern = re.compile(rf"\b{re.escape(drug_name.strip())}\b", re.IGNORECASE)
        buttons = page.locator("button.cursor-pointer:visible")
        count = await buttons.count()

        best_index = None
        best_score = -1

        for idx in range(count):
            button = buttons.nth(idx)
            try:
                text = (await button.inner_text()).strip()
            except Exception:
                continue

            if not text or not pattern.search(text):
                continue

            normalized = " ".join(text.upper().split())
            if normalized == query:
                score = 3
            elif normalized.startswith(f"{query} (") or normalized.startswith(f"{query} +"):
                score = 2
            else:
                score = 1

            if score > best_score:
                best_score = score
                best_index = idx
                if score == 3:
                    break

        if best_index is None:
            return None

        return buttons.nth(best_index)

    @staticmethod
    async def search_drug(drug_name: str) -> Optional[Dict]:
        """
        Search for a drug on PNDF website using Playwright
        Handles JavaScript-rendered content and Radix dialogs
        
        Returns dict with drug information or None if not found
        """
        if not PLAYWRIGHT_AVAILABLE:
            logger.error("Playwright not available. Install with: pip install playwright && playwright install chromium")
            return PNDFScraper._error_result(
                drug_name,
                error="Playwright not available",
                error_code="playwright_unavailable",
                message="Scraper runtime unavailable",
            )
>>>>>>> d051e7d6b3726db590b9f026cd179df9d0975181

        Returns a dict compatible with PNDFEnrichmentItem, or None if not found.
        """
        if not PATCHRIGHT_AVAILABLE:
            logger.error(
                "patchright not installed. Run: pip install patchright && patchright install chromium"
            )
<<<<<<< HEAD
            return None

        try:
            loop = asyncio.get_event_loop()
            raw_results: List[Dict] = await loop.run_in_executor(
                None, _scrape_drug_sync, drug_name
            )
        except Exception as exc:
            logger.error(f"[pndf] Error scraping '{drug_name}': {exc}")
=======
            
            page = await context.new_page()
            
            logger.info(f"Searching PNDF for: {drug_name}")
            
            # Navigate to the site with retry logic for network errors
            max_retries = 3
            retry_delay = 2  # seconds
            navigation_success = False
            
            for attempt in range(1, max_retries + 1):
                try:
                    logger.info(f"Attempting to navigate to {PNDF_BASE_URL} (attempt {attempt}/{max_retries})...")
                    await page.goto(PNDF_BASE_URL, wait_until="domcontentloaded", timeout=60000)
                    navigation_success = True
                    logger.info("Page loaded, checking for Cloudflare challenge...")
                    break
                except Exception as nav_error:
                    error_msg = str(nav_error)
                    # Check if it's a network/DNS error
                    if "ERR_NAME_NOT_RESOLVED" in error_msg or "net::" in error_msg:
                        if attempt < max_retries:
                            wait_time = retry_delay * attempt
                            logger.warning(
                                f"Network error (attempt {attempt}/{max_retries}): {error_msg}. "
                                f"Retrying in {wait_time} seconds..."
                            )
                            await asyncio.sleep(wait_time)
                        else:
                            logger.error(
                                f"Failed to resolve DNS or connect to {PNDF_BASE_URL} after {max_retries} attempts. "
                                f"Error: {error_msg}. Please check your internet connection and verify the site is accessible."
                            )
                            error_code = "dns_error" if "ERR_NAME_NOT_RESOLVED" in error_msg else "network_error"
                            return PNDFScraper._error_result(
                                drug_name,
                                error=error_msg,
                                error_code=error_code,
                                message=f"Could not connect to PNDF portal ({PNDF_BASE_URL})",
                            )
                    else:
                        # For non-network errors, don't retry
                        logger.error(f"Navigation error: {error_msg}")
                        raise
            
            if not navigation_success:
                logger.error(f"Failed to navigate to {PNDF_BASE_URL} after {max_retries} attempts")
                return PNDFScraper._error_result(
                    drug_name,
                    error=f"Failed to navigate to {PNDF_BASE_URL}",
                    error_code="network_error",
                )
            
            # Wait a bit for page to fully load
            await page.wait_for_timeout(2000)
            
            # Check if Cloudflare challenge page appeared
            page_title = await page.title()
            if "Cloudflare" in page_title or "Attention Required" in page_title:
                logger.warning("Cloudflare challenge detected, waiting for it to resolve (this may take 5-30 seconds)...")
                # Wait for Cloudflare challenge to complete
                try:
                    # Wait for the page title to change from Cloudflare challenge
                    await page.wait_for_function(
                        "document.title !== 'Attention Required! | Cloudflare' && !document.title.includes('Cloudflare')",
                        timeout=35000
                    )
                    logger.info("Cloudflare challenge resolved")
                    await page.wait_for_timeout(2000)  # Extra wait after challenge
                except PlaywrightTimeoutError:
                    logger.error("Cloudflare challenge did not resolve in time - may need manual intervention")
                    # Try to wait a bit more and check again
                    await page.wait_for_timeout(5000)
                    page_title = await page.title()
                    if "Cloudflare" in page_title or "Attention Required" in page_title:
                        logger.error("Still blocked by Cloudflare. Consider running with headless=False for manual challenge completion.")
                        return PNDFScraper._error_result(
                            drug_name,
                            error="Blocked by Cloudflare challenge",
                            error_code="cloudflare_blocked",
                            message="PNDF access is blocked by Cloudflare challenge",
                        )
                except Exception as e:
                    logger.warning(f"Error waiting for Cloudflare challenge: {e}")
            
            logger.info("Waiting for JavaScript to execute...")
            
            # Handle Radix dialog that appears on refresh
            await PNDFScraper._handle_radix_dialog(page)
            
            # Wait a bit more after dialog handling
            await page.wait_for_timeout(500)
            
            # Wait for search input to be available and visible
            search_input_locator = None
            try:
                await page.wait_for_selector('#inputGlobalSearch', timeout=15000, state="attached")
                logger.info("Search input found in DOM")

                search_input_locator = page.locator('#inputGlobalSearch')
                await search_input_locator.wait_for(state="visible", timeout=10000)
                await search_input_locator.scroll_into_view_if_needed()
                await page.wait_for_timeout(300)
                logger.info("Search input is visible and ready")
            except PlaywrightTimeoutError as e:
                logger.error(f"Search input #inputGlobalSearch not found or not visible: {e}")
                try:
                    logger.info("Trying fallback: searching by placeholder text...")
                    search_input_locator = page.locator('input[placeholder*="generic name"]').first
                    await search_input_locator.wait_for(state="visible", timeout=5000)
                    await search_input_locator.scroll_into_view_if_needed()
                    logger.info("Found search input by placeholder text")
                except PlaywrightTimeoutError:
                    logger.error("Could not find search input by ID or placeholder")
                    return PNDFScraper._error_result(
                        drug_name,
                        error="PNDF search input not found",
                        error_code="selector_not_found",
                    )

            if search_input_locator is None:
                logger.error("Search input locator is None, cannot proceed")
                return PNDFScraper._error_result(
                    drug_name,
                    error="PNDF search input locator unavailable",
                    error_code="selector_not_found",
                )

            search_input = search_input_locator

            # Ensure any modal blocking pointer events is closed before typing
            await PNDFScraper._handle_radix_dialog(page)

            # Fill value and verify it actually sticks (critical on this site)
            await search_input.click(timeout=5000, force=True)
            await search_input.fill("")
            await search_input.type(drug_name, delay=25)
            typed_value = (await search_input.input_value()).strip()

            if typed_value.lower() != drug_name.strip().lower():
                logger.warning(
                    f"Search input value mismatch after type. Expected '{drug_name}', got '{typed_value}'. Retrying with fill()"
                )
                await search_input.fill(drug_name)
                typed_value = (await search_input.input_value()).strip()

            if typed_value.lower() != drug_name.strip().lower():
                logger.error(
                    f"Search input did not accept query reliably. Expected '{drug_name}', got '{typed_value}'"
                )
                return PNDFScraper._error_result(
                    drug_name,
                    error=f"PNDF search input rejected query: {typed_value}",
                    error_code="selector_not_found",
                    message="PNDF search field did not accept the medication query",
                )

            await page.wait_for_timeout(200)

            # Click the main Search action (not Apply Filters)
            clicked = False
            search_button_candidates = [
                page.locator('button.bg-sambong:has-text("Search")').first,
                page.locator('button:has-text("Search"):not(:has-text("Apply Filters"))').first,
            ]

            for candidate in search_button_candidates:
                try:
                    if await candidate.count() and await candidate.is_visible(timeout=1500):
                        await candidate.click(timeout=5000)
                        clicked = True
                        logger.info("Clicked search button")
                        break
                except Exception as click_err:
                    logger.debug(f"Search button candidate failed: {click_err}")

            if not clicked:
                await search_input.press("Enter")
                logger.info("Search button click failed; pressed Enter on search input")

            # Wait for result list refresh
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except PlaywrightTimeoutError:
                logger.debug("networkidle timeout after search; continuing with current DOM")

            await page.wait_for_timeout(2000)

            # Expand matching result card (if present) to expose details sections
            logger.info("Looking for disclosure/accordion button to expand drug details...")
            disclosure_button = await PNDFScraper._find_disclosure_button(page, drug_name)

            if disclosure_button is not None:
                try:
                    await disclosure_button.scroll_into_view_if_needed(timeout=3000)
                except Exception:
                    pass

                clicked_disclosure = False
                try:
                    await disclosure_button.click(timeout=3000)
                    clicked_disclosure = True
                    logger.info(f"Expanded result card for {drug_name}")
                except Exception as click_error:
                    logger.debug(f"Normal disclosure click failed: {click_error}")

                if not clicked_disclosure:
                    try:
                        await disclosure_button.click(timeout=3000, force=True)
                        clicked_disclosure = True
                        logger.info(f"Expanded result card with force click for {drug_name}")
                    except Exception as force_error:
                        logger.warning(f"Could not expand disclosure button for {drug_name}: {force_error}")

                if clicked_disclosure:
                    await page.wait_for_timeout(1500)
            else:
                logger.warning(f"No visible matching disclosure button found for {drug_name}")

            # Get page HTML after JavaScript execution and optional expansion
            html_content = await page.content()
            
            # Debug HTML snapshots are disabled by default.
            if PNDF_SAVE_DEBUG_HTML:
                debug_html_path = CACHE_DIR / f"debug_{PNDFScraper._safe_filename(drug_name)}_page.html"
                try:
                    CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    with open(debug_html_path, "w", encoding="utf-8") as f:
                        f.write(html_content)
                    logger.debug(f"Saved page HTML to {debug_html_path} for debugging")
                except Exception as e:
                    logger.debug(f"Could not save debug HTML: {e}")
            
            # Parse HTML with BeautifulSoup
            soup = BeautifulSoup(html_content, "lxml")
            
            # Extract drug information
            drug_info = PNDFScraper._parse_drug_page(soup, drug_name)

            if drug_info:
                logger.info(f"Found drug: {drug_name}")
                return drug_info
            else:
                logger.info(f"Drug not found: {drug_name}")
                return None

        except PlaywrightTimeoutError as e:
            logger.error(f"Timeout error searching for {drug_name}: {e}")
            return PNDFScraper._error_result(
                drug_name,
                error=str(e),
                error_code="timeout",
                message="PNDF page interaction timed out",
            )
        except Exception as e:
            error_msg = str(e)
            # Provide more helpful error messages for common network issues
            if "ERR_NAME_NOT_RESOLVED" in error_msg:
                logger.error(
                    f"DNS resolution failed for {PNDF_BASE_URL}. "
                    f"This could indicate: network connectivity issues, DNS problems, or the site may be down. "
                    f"Error: {error_msg}"
                )
                return PNDFScraper._error_result(
                    drug_name,
                    error=error_msg,
                    error_code="dns_error",
                    message=f"Could not resolve {PNDF_BASE_URL}",
                )
            elif "net::" in error_msg:
                logger.error(
                    f"Network error while searching for {drug_name}: {error_msg}. "
                    f"Please check your internet connection and try again."
                )
                return PNDFScraper._error_result(
                    drug_name,
                    error=error_msg,
                    error_code="network_error",
                    message="Network error while reaching PNDF portal",
                )
            else:
                logger.error(f"Error searching for {drug_name}: {error_msg}")
                return PNDFScraper._error_result(
                    drug_name,
                    error=error_msg,
                    error_code="scrape_error",
                )
        finally:
            # Always close the page and context to free resources
            if page:
                try:
                    await page.close()
                except Exception as e:
                    logger.debug(f"Error closing page: {e}")
            if context:
                try:
                    await context.close()
                except Exception as e:
                    logger.debug(f"Error closing context: {e}")

    @staticmethod
    def _parse_drug_page(soup: BeautifulSoup, drug_name: str) -> Optional[Dict]:
        """
        Parse drug information from HTML page.
        Extract classification, dosage, interactions, etc.
        """
        try:
            drug_info = {
                "name": drug_name.upper(),
                "found": True,
                "atc_code": None,
                "classification": {
                    "anatomical": None,
                    "therapeutic": None,
                    "pharmacological": None,
                    "chemical_class": None,
                },
                "dosage_forms": [],
                "indications": None,
                "contraindications": None,
                "precautions": None,
                "adverse_reactions": None,
                "drug_interactions": None,
                "mechanism_of_action": None,
                "dosage_instructions": None,
                "administration": None,
                "pregnancy_category": None,
                "scraped_at": datetime.now().isoformat(),
            }

            # Keep newlines so regex/section extraction remains robust on minified DOM.
            full_text = soup.get_text("\n", strip=True)
            page_text = full_text.lower()
            drug_name_lower = drug_name.lower()

            if drug_name_lower not in page_text:
                logger.debug(f"Drug name '{drug_name}' not found anywhere in page text")
                logger.debug(f"Page text sample: {full_text[:500]}")
                return None

            logger.debug(f"Drug name '{drug_name}' found in page text, proceeding with extraction")

            # Extract ATC code (supports both "ATC Code: N02..." and "ATC Code N02...").
            atc_match = re.search(
                r"\bATC\s*Code\b\s*:?\s*([A-Z]\d{2}[A-Z]{2}\d{2})",
                full_text,
                re.IGNORECASE,
            )
            if atc_match:
                drug_info["atc_code"] = atc_match.group(1)

            # Extract classifications.
            classifications = {
                "Anatomical": "anatomical",
                "Therapeutic": "therapeutic",
                "Pharmacological": "pharmacological",
                "Chemical Class": "chemical_class",
            }

            for key, field in classifications.items():
                pattern = rf"\b{re.escape(key)}\b\s*:?\s*([^\n]+)"
                match = re.search(pattern, full_text, re.IGNORECASE)
                if match:
                    drug_info["classification"][field] = match.group(1).strip()

            # Extract dosage forms (e.g. "ORAL > 500 mg tablet (OTC)").
            dosage_pattern = r"(ORAL|RECTAL|IM|IV|INTRA|TOPICAL)\s*[>\u203A:\-]\s*([^\n(]+)\(([^)]+)\)"
            dosage_matches = re.findall(dosage_pattern, full_text, re.IGNORECASE)
            for route, form, status in dosage_matches:
                drug_info["dosage_forms"].append(
                    {
                        "route": route.strip().upper(),
                        "form": form.strip(),
                        "status": status.strip(),
                    }
                )

            sections = {
                "Indications": "indications",
                "Contraindications": "contraindications",
                "Precautions": "precautions",
                "Adverse Drug Reactions": "adverse_reactions",
                "Drug Interactions": "drug_interactions",
                "Mechanism of Action": "mechanism_of_action",
                "Dosage": "dosage_instructions",
                "Administration": "administration",
                "Pregnancy Category": "pregnancy_category",
            }

            # Pass 1: text-line extraction.
            lines = [line.strip() for line in full_text.splitlines() if line.strip()]
            for section_name, field_key in sections.items():
                header_pattern = rf"^{re.escape(section_name)}\s*$"

                for i, line in enumerate(lines):
                    if not re.match(header_pattern, line, re.IGNORECASE):
                        continue

                    content_lines = []
                    j = i + 1
                    while j < len(lines):
                        next_line = lines[j]
                        if any(
                            re.match(rf"^{re.escape(section)}\s*$", next_line, re.IGNORECASE)
                            for section in sections.keys()
                        ):
                            break
                        content_lines.append(next_line)
                        j += 1

                    if content_lines:
                        drug_info[field_key] = " ".join(content_lines)[:1000]
                    break

            # Pass 2: heading-based extraction for the current PNDF detail card layout.
            for section_name, field_key in sections.items():
                if drug_info[field_key]:
                    continue

                heading = soup.find(
                    lambda tag: tag.name in {"h2", "h3", "h4"}
                    and section_name.lower() in tag.get_text(" ", strip=True).lower()
                )
                if not heading:
                    continue

                if section_name == "Dosage":
                    content_node = heading.find_next(
                        lambda tag: tag.name in {"div", "p"} and tag.get_text(" ", strip=True)
                    )
                else:
                    content_node = heading.find_next("p")

                if not content_node:
                    continue

                content_text = " ".join(content_node.get_text(" ", strip=True).split())
                if content_text:
                    drug_info[field_key] = content_text[:1000]

            return drug_info

        except Exception as e:
            logger.error(f"Error parsing drug page: {e}")
>>>>>>> d051e7d6b3726db590b9f026cd179df9d0975181
            return None

        if not raw_results:
            return None

        # Return the first (best) match converted to enrichment format
        return _details_to_enrichment(raw_results[0])

    @staticmethod
    async def load_cache() -> List[Dict]:
        cache = await load_cache(CACHE_PATH, ttl_seconds=PNDFScraper.CACHE_TTL_SECONDS)
        logger.info(f"Loaded PNDF cache with {len(cache)} drugs")
        return cache

    @staticmethod
    async def save_cache(data: List[Dict]) -> None:
        saved = await save_cache(CACHE_PATH, data, key_fn=PNDFScraper._cache_key)
        logger.info(f"Saved PNDF cache with {len(saved)} drugs")

    @staticmethod
    async def enrich_medications(
        drug_names: List[str], cache: Optional[List[Dict]] = None
    ) -> List[Dict]:
        """
        Enrich a list of drug names with PNDF data.
        Checks cache first; scrapes live for misses.
        """
        if cache is None:
            cache = await PNDFScraper.load_cache()

<<<<<<< HEAD
=======
        enriched: List[Dict] = [{"name": drug_name, "found": False} for drug_name in drug_names]
>>>>>>> d051e7d6b3726db590b9f026cd179df9d0975181
        cache_dict = {
            normalize_key(drug.get("name", "")): drug
            for drug in cache
            if normalize_key(drug.get("name", ""))
        }
        pending: List[Tuple[int, str, str]] = []

<<<<<<< HEAD
        enriched = []
        for drug_name in drug_names:
            key = normalize_key(drug_name)
            cached = cache_dict.get(key)
            if cached:
                enriched.append(cached)
                logger.info(f"[pndf] Cache hit: {drug_name}")
            else:
                logger.info(f"[pndf] Cache miss, scraping: {drug_name}")
                try:
                    drug_info = await PNDFScraper.search_drug(drug_name)
                    if drug_info:
                        enriched.append(drug_info)
                        cache = await upsert_cache_entry(
                            CACHE_PATH, drug_info, key_fn=PNDFScraper._cache_key
                        )
                        cache_dict[key] = drug_info
                    else:
                        error_code = (
                            "patchright_unavailable"
                            if not PATCHRIGHT_AVAILABLE
                            else "not_found"
                        )
                        enriched.append({
                            "name": drug_name,
                            "found": False,
                            "message": (
                                "Scraper runtime unavailable"
                                if error_code == "patchright_unavailable"
                                else "Not found in PNDF database"
                            ),
                            "error_code": error_code,
                        })
                except Exception as exc:
                    logger.error(f"[pndf] Error enriching '{drug_name}': {exc}")
                    enriched.append({
                        "name": drug_name,
                        "found": False,
                        "error": str(exc),
                        "error_code": "scrape_error",
                    })
=======
        for idx, drug_name in enumerate(drug_names):
            drug_name_key = normalize_key(drug_name)

            cached_drug = cache_dict.get(drug_name_key)
            if cached_drug:
                enriched[idx] = cached_drug
                logger.info(f"Found {drug_name} in cache")
            elif PNDFScraper._is_negative_cache_hit(drug_name_key):
                enriched[idx] = {
                    "name": drug_name,
                    "found": False,
                    "message": "Skipped PNDF retry after recent miss/error",
                    "error_code": "recent_miss_cache",
                    "scraped_at": datetime.now().isoformat(),
                }
                logger.info(f"Skipping PNDF lookup for {drug_name} due to recent miss/error cache")
            else:
                pending.append((idx, drug_name, drug_name_key))

        if pending:
            semaphore = asyncio.Semaphore(PNDFScraper.LOOKUP_CONCURRENCY)

            async def _lookup(index: int, drug_name: str, drug_name_key: str) -> None:
                async with semaphore:
                    logger.info(f"Searching for {drug_name} (not in cache)...")
                    try:
                        if PNDFScraper.LOOKUP_TIMEOUT_SECONDS > 0:
                            search_task = asyncio.create_task(PNDFScraper.search_drug(drug_name))
                            done, _ = await asyncio.wait(
                                {search_task},
                                timeout=PNDFScraper.LOOKUP_TIMEOUT_SECONDS,
                            )
                            if search_task not in done:
                                search_task.cancel()
                                raise asyncio.TimeoutError
                            drug_info = search_task.result()
                        else:
                            drug_info = await PNDFScraper.search_drug(drug_name)
                        if drug_info and (drug_info.get("error_code") or drug_info.get("error")):
                            PNDFScraper._remember_negative_lookup(drug_name_key)
                            enriched[index] = {
                                "name": str(drug_info.get("name") or drug_name),
                                "found": False,
                                "message": str(
                                    drug_info.get("message")
                                    or drug_info.get("error")
                                    or "PNDF lookup failed"
                                ),
                                "error": drug_info.get("error"),
                                "error_code": str(drug_info.get("error_code") or "scrape_error"),
                                "scraped_at": str(drug_info.get("scraped_at") or datetime.now().isoformat()),
                            }
                        elif drug_info:
                            enriched[index] = drug_info
                            await upsert_cache_entry(
                                CACHE_PATH,
                                drug_info,
                                key_fn=PNDFScraper._cache_key,
                            )
                            cache_dict[drug_name_key] = drug_info
                        else:
                            PNDFScraper._remember_negative_lookup(drug_name_key)
                            error_code = "playwright_unavailable" if not PLAYWRIGHT_AVAILABLE else "not_found"
                            message = (
                                "Scraper runtime unavailable"
                                if error_code == "playwright_unavailable"
                                else "Not found in PNDF database"
                            )
                            enriched[index] = {
                                "name": drug_name,
                                "found": False,
                                "message": message,
                                "error_code": error_code,
                                "scraped_at": datetime.now().isoformat(),
                            }
                    except asyncio.TimeoutError:
                        PNDFScraper._remember_negative_lookup(drug_name_key)
                        enriched[index] = {
                            "name": drug_name,
                            "found": False,
                            "message": (
                                "PNDF lookup timed out after "
                                f"{PNDFScraper.LOOKUP_TIMEOUT_SECONDS:.1f}s"
                            ),
                            "error_code": "timeout",
                            "scraped_at": datetime.now().isoformat(),
                        }
                    except Exception as e:
                        logger.error(f"Error enriching {drug_name}: {e}")
                        PNDFScraper._remember_negative_lookup(drug_name_key)
                        enriched[index] = {
                            "name": drug_name,
                            "found": False,
                            "error": str(e),
                            "error_code": "scrape_error",
                            "scraped_at": datetime.now().isoformat(),
                        }
>>>>>>> d051e7d6b3726db590b9f026cd179df9d0975181

                    if PNDFScraper.REQUEST_DELAY > 0:
                        await asyncio.sleep(PNDFScraper.REQUEST_DELAY)

            await asyncio.gather(*(_lookup(index, name, key) for index, name, key in pending))

        return enriched

    @staticmethod
    async def refresh_cache(drugs_to_fetch: Optional[List[str]] = None) -> None:
        """Pre-warm the cache for a list of common drugs."""
        default_drugs = [
            "paracetamol",
            "ibuprofen",
            "aspirin",
            "amoxicillin",
            "metformin",
            "lisinopril",
            "atorvastatin",
            "omeprazole",
            "loratadine",
            "cetirizine",
        ]
        drugs = drugs_to_fetch or default_drugs
        logger.info(f"[pndf] Starting cache refresh for {len(drugs)} drugs …")

        cache = await PNDFScraper.load_cache()
        cache_dict = {
            normalize_key(drug.get("name", "")): drug
            for drug in cache
            if normalize_key(drug.get("name", ""))
        }

        for drug_name in drugs:
            if normalize_key(drug_name) not in cache_dict:
                try:
                    drug_info = await PNDFScraper.search_drug(drug_name)
                    if drug_info:
                        cache = await upsert_cache_entry(
                            CACHE_PATH, drug_info, key_fn=PNDFScraper._cache_key
                        )
                        cache_dict[normalize_key(drug_name)] = drug_info
                except Exception as exc:
                    logger.error(f"[pndf] Error refreshing '{drug_name}': {exc}")

                await asyncio.sleep(PNDFScraper.REQUEST_DELAY)

        logger.info(f"[pndf] Cache refresh complete. Total: {len(cache_dict)} drugs.")

    @staticmethod
    async def cleanup():
<<<<<<< HEAD
        """No-op: patchright browser is opened/closed per search call."""
        logger.info("[pndf] PNDF scraper cleanup complete (nothing to close).")
=======
        """Clean up browser resources (call on server shutdown)"""
        await PNDFScraper._close_browser()
        PNDFScraper._negative_cache.clear()
        logger.info("PNDF scraper cleanup complete")

>>>>>>> d051e7d6b3726db590b9f026cd179df9d0975181
