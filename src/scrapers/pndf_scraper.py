"""
Philippine National Drug Formulary (PNDF) Web Scraper
Fetches and parses medication information from https://pnf.doh.gov.ph/
Uses Playwright to handle JavaScript-rendered content (Next.js with Radix dialogs)
"""

import json
import logging
import asyncio
import os
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
from bs4 import BeautifulSoup
import re

logger = logging.getLogger(__name__)

try:
    from playwright.async_api import async_playwright, Browser, Page, TimeoutError as PlaywrightTimeoutError
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("Playwright not installed. Install with: pip install playwright && playwright install chromium")

CACHE_DIR = Path("./data")
CACHE_PATH = CACHE_DIR / "pndf_cache.json"
PNDF_BASE_URL = "https://pnf.doh.gov.ph"

# Cloudflare bypass: Set to False to avoid detection (browser window will be visible)
# Set PNDF_HEADLESS=false environment variable to run in visible mode
PNDF_HEADLESS = os.getenv("PNDF_HEADLESS", "true").lower() == "false"


class PNDFScraper:
    """Scraper for Philippine National Drug Formulary using Playwright for JS-rendered content"""

    # Request delay (seconds) between searches to respect server
    REQUEST_DELAY = 0.5
    
    # Shared browser instance (initialized lazily)
    _browser: Optional[Browser] = None
    _playwright_context = None

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
                headless=not PNDF_HEADLESS,  # Use False to bypass Cloudflare (browser window visible)
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
        Handle Disclaimer Modal (Radix dialog) that appears on page refresh
        The modal blocks the page, so it must be closed before interacting with elements
        """
        try:
            # Wait a bit for dialog to appear
            await page.wait_for_timeout(1000)
            
            # First, check if the disclaimer modal exists by looking for the radix dialog
            # The modal has id="radix-_r_9_" or similar with data-state="open"
            try:
                # Check for open Radix dialog
                open_dialog = page.locator('[id^="radix-"][data-state="open"]').first
                if await open_dialog.is_visible(timeout=2000):
                    logger.info("Found open Radix dialog (Disclaimer Modal)")
                    
                    # Try the most robust method: getByRole with exact 'Close' button
                    try:
                        close_button = page.get_by_role('button', name='Close')
                        if await close_button.is_visible(timeout=2000):
                            logger.info("Found Close button using getByRole")
                            await close_button.click()
                            await page.wait_for_timeout(500)
                            # Verify dialog closed
                            try:
                                if not await open_dialog.is_visible(timeout=1000):
                                    logger.info("✓ Disclaimer Modal closed successfully")
                                    return
                            except:
                                logger.info("✓ Disclaimer Modal appears to be closed")
                                return
                    except PlaywrightTimeoutError:
                        logger.debug("Close button not found with getByRole, trying other methods...")
                    
                    # Fallback selectors if getByRole doesn't work
                    fallback_selectors = [
                        'button[aria-label="Close"]',
                        'button[data-radix-dialog-close]',
                        '[role="dialog"] button:has-text("Close")',
                    ]
                    
                    for selector in fallback_selectors:
                        try:
                            close_button = page.locator(selector).first
                            if await close_button.is_visible(timeout=1000):
                                logger.info(f"Found dialog close button: {selector}")
                                await close_button.click()
                                await page.wait_for_timeout(500)
                                logger.info("✓ Dialog closed with fallback method")
                                return
                        except PlaywrightTimeoutError:
                            continue
                    
                    # Last resort: Try pressing Escape
                    logger.info("Trying Escape key to close dialog")
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(500)
                    logger.info("Pressed Escape to close dialog")
                    
            except PlaywrightTimeoutError:
                # No open dialog found
                logger.debug("No open Radix dialog found (or already closed)")
            
        except Exception as e:
            logger.debug(f"Error handling dialog (may not exist): {e}")

    @staticmethod
    async def search_drug(drug_name: str) -> Optional[Dict]:
        """
        Search for a drug on PNDF website using Playwright
        Handles JavaScript-rendered content and Radix dialogs
        
        Returns dict with drug information or None if not found
        """
        if not PLAYWRIGHT_AVAILABLE:
            logger.error("Playwright not available. Install with: pip install playwright && playwright install chromium")
            return None

        page = None
        context = None
        try:
            browser = await PNDFScraper._get_browser()
            
            # Create a context with realistic user agent and settings to avoid Cloudflare detection
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={"width": 1920, "height": 1080},
                extra_http_headers={
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                }
            )
            
            page = await context.new_page()
            
            logger.info(f"Searching PNDF for: {drug_name}")
            
            # Navigate to the site
            await page.goto(PNDF_BASE_URL, wait_until="domcontentloaded", timeout=60000)
            logger.info("Page loaded, checking for Cloudflare challenge...")
            
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
                    logger.info("✓ Cloudflare challenge resolved")
                    await page.wait_for_timeout(2000)  # Extra wait after challenge
                except PlaywrightTimeoutError:
                    logger.error("Cloudflare challenge did not resolve in time - may need manual intervention")
                    # Try to wait a bit more and check again
                    await page.wait_for_timeout(5000)
                    page_title = await page.title()
                    if "Cloudflare" in page_title or "Attention Required" in page_title:
                        logger.error("Still blocked by Cloudflare. Consider running with headless=False for manual challenge completion.")
                        return None
                except Exception as e:
                    logger.warning(f"Error waiting for Cloudflare challenge: {e}")
            
            logger.info("Waiting for JavaScript to execute...")
            
            # Handle Radix dialog that appears on refresh
            await PNDFScraper._handle_radix_dialog(page)
            
            # Wait a bit more after dialog handling
            await page.wait_for_timeout(500)
            
            # Wait for search input to be available and visible
            # First check if it exists in DOM, then ensure it's visible
            search_input_locator = None
            try:
                # Wait for selector to exist
                await page.wait_for_selector('#inputGlobalSearch', timeout=15000, state="attached")
                logger.info("Search input found in DOM")
                
                # Wait for it to be visible (not hidden by dialog or loading)
                search_input_locator = page.locator('#inputGlobalSearch')
                await search_input_locator.wait_for(state="visible", timeout=10000)
                
                # Scroll to make sure it's in viewport
                await search_input_locator.scroll_into_view_if_needed()
                await page.wait_for_timeout(300)
                
                logger.info("Search input is visible and ready")
            except PlaywrightTimeoutError as e:
                # Try to get page content for debugging
                logger.error(f"Search input #inputGlobalSearch not found or not visible: {e}")
                # Check what's actually on the page
                try:
                    page_title = await page.title()
                    page_url = page.url
                    logger.error(f"Current page title: {page_title}, URL: {page_url}")
                    # Check if there are any inputs at all
                    input_count = await page.locator('input').count()
                    logger.error(f"Total inputs on page: {input_count}")
                    if input_count > 0:
                        # List all input IDs
                        all_inputs = await page.locator('input').all()
                        for i, inp in enumerate(all_inputs[:5]):  # First 5 inputs
                            try:
                                input_id = await inp.get_attribute('id')
                                input_placeholder = await inp.get_attribute('placeholder')
                                logger.error(f"Input {i}: id='{input_id}', placeholder='{input_placeholder}'")
                            except:
                                pass
                except Exception as debug_error:
                    logger.debug(f"Could not get debug info: {debug_error}")
                
                # Try fallback: search by placeholder text
                try:
                    logger.info("Trying fallback: searching by placeholder text...")
                    search_input_locator = page.locator('input[placeholder*="generic name"]').first
                    await search_input_locator.wait_for(state="visible", timeout=5000)
                    await search_input_locator.scroll_into_view_if_needed()
                    logger.info("Found search input by placeholder text")
                except PlaywrightTimeoutError:
                    logger.error("Could not find search input by ID or placeholder")
                    return None
            
            # At this point, search_input_locator should be defined
            if search_input_locator is None:
                logger.error("Search input locator is None, cannot proceed")
                return None
            
            # Type drug name in search input
            search_input = search_input_locator
            await search_input.fill(drug_name)
            await page.wait_for_timeout(300)  # Small delay after typing
            
            # Find and click the search button using getByRole (most robust method)
            # Using exact: true ensures we click the actual "Search" button, not other buttons with "Search" in the text
            try:
                search_button = page.get_by_role('button', name='Search', exact=True)
                if await search_button.is_visible(timeout=2000):
                    await search_button.click()
                    logger.info("Clicked search button using getByRole")
                else:
                    # Fallback: try pressing Enter
                    await search_input.press("Enter")
                    logger.info("Search button not visible, pressed Enter on search input")
            except PlaywrightTimeoutError:
                # Fallback: try pressing Enter or use CSS selector
                try:
                    logger.info("getByRole failed, trying CSS selector fallback...")
                    search_button = page.locator('button:has-text("Search")').first
                    if await search_button.is_visible(timeout=1000):
                        await search_button.click()
                        logger.info("Clicked search button using CSS selector fallback")
                    else:
                        await search_input.press("Enter")
                        logger.info("CSS selector failed, pressed Enter on search input")
                except:
                    await search_input.press("Enter")
                    logger.info("All methods failed, pressed Enter on search input")
                
            # Wait for search results to load
            # Wait for navigation/network activity to settle
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
                await page.wait_for_timeout(1500)  # Extra wait for dynamic content to render
                logger.info("Waiting for search results to load...")
            except PlaywrightTimeoutError:
                logger.warning("Page may still be loading, proceeding anyway...")
            
            # Get page HTML after JavaScript execution
            html_content = await page.content()
            
            # Parse HTML with BeautifulSoup
            soup = BeautifulSoup(html_content, "lxml")
            
            # Extract drug information
            drug_info = PNDFScraper._parse_drug_page(soup, drug_name)

            if drug_info:
                logger.info(f"✓ Found drug: {drug_name}")
                return drug_info
            else:
                logger.info(f"✗ Drug not found: {drug_name}")
                return None

        except PlaywrightTimeoutError as e:
            logger.error(f"Timeout error searching for {drug_name}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error searching for {drug_name}: {e}")
            return None
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
        Parse drug information from HTML page
        Extract classification, dosage, interactions, etc.
        """
        try:
            drug_info = {
                "name": drug_name.upper(),
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

            # Try to find drug name section
            drug_section = soup.find(
                lambda tag: tag.name and drug_name.lower() in tag.get_text().lower()
            )

            if not drug_section:
                return None

            # Extract ATC Code
            atc_match = re.search(r"ATC Code[:\s]+([A-Z]\d{2}[A-Z]{2}\d{2})", soup.get_text())
            if atc_match:
                drug_info["atc_code"] = atc_match.group(1)

            # Extract classifications
            classifications = {
                "Anatomical": "anatomical",
                "Therapeutic": "therapeutic",
                "Pharmacological": "pharmacological",
                "Chemical Class": "chemical_class",
            }

            for key, field in classifications.items():
                pattern = rf"{key}[:\s]+([^\n]+)"
                match = re.search(pattern, soup.get_text(), re.IGNORECASE)
                if match:
                    drug_info["classification"][field] = match.group(1).strip()

            # Extract dosage forms (look for ORAL, RECTAL, IM, IV patterns)
            dosage_pattern = r"(ORAL|RECTAL|IM|IV|INTRA|TOPICAL)[›:\s]+([^\n(]+)\(([^)]+)\)"
            dosage_matches = re.findall(dosage_pattern, soup.get_text())
            for route, form, status in dosage_matches:
                drug_info["dosage_forms"].append({
                    "route": route.strip(),
                    "form": form.strip(),
                    "status": status.strip(),
                })

            # Extract sections using headers
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

            for section_name, field_key in sections.items():
                # Find section header
                header_pattern = rf"^{section_name}\s*$"
                lines = soup.get_text().split("\n")
                
                for i, line in enumerate(lines):
                    if re.match(header_pattern, line.strip(), re.IGNORECASE):
                        # Collect content until next section header
                        content_lines = []
                        j = i + 1
                        while j < len(lines):
                            next_line = lines[j].strip()
                            # Stop if we hit another section header
                            if any(
                                re.match(rf"^{s}\s*$", next_line, re.IGNORECASE)
                                for s in sections.keys()
                            ):
                                break
                            if next_line:
                                content_lines.append(next_line)
                            j += 1
                        
                        if content_lines:
                            drug_info[field_key] = " ".join(content_lines)[:500]  # Limit length
                        break

            return drug_info

        except Exception as e:
            logger.error(f"Error parsing drug page: {e}")
            return None

    @staticmethod
    async def load_cache() -> List[Dict]:
        """Load cached PNDF data from disk"""
        if CACHE_PATH.exists():
            try:
                with open(CACHE_PATH, "r") as f:
                    cache = json.load(f)
                    logger.info(f"✓ Loaded PNDF cache with {len(cache)} drugs")
                    return cache
            except Exception as e:
                logger.error(f"Error loading cache: {e}")
        return []

    @staticmethod
    async def save_cache(data: List[Dict]) -> None:
        """Persist PNDF data to disk"""
        try:
            CACHE_DIR.mkdir(exist_ok=True)
            with open(CACHE_PATH, "w") as f:
                json.dump(data, f, indent=2)
            logger.info(f"✓ Saved PNDF cache with {len(data)} drugs")
        except Exception as e:
            logger.error(f"Error saving cache: {e}")

    @staticmethod
    async def enrich_medications(
        drug_names: List[str], cache: Optional[List[Dict]] = None
    ) -> List[Dict]:
        """
        Enrich medication list with PNDF data
        Uses cache first, then searches live if not found
        """
        if cache is None:
            cache = await PNDFScraper.load_cache()

        enriched = []
        cache_dict = {drug["name"].lower(): drug for drug in cache}

        for drug_name in drug_names:
            drug_name_lower = drug_name.lower()

            # Try to find in cache
            cached_drug = cache_dict.get(drug_name_lower)
            if cached_drug:
                enriched.append(cached_drug)
                logger.info(f"✓ Found {drug_name} in cache")
            else:
                # Try to search live
                logger.info(f"Searching for {drug_name} (not in cache)...")
                try:
                    drug_info = await PNDFScraper.search_drug(drug_name)
                    if drug_info:
                        enriched.append(drug_info)
                        # Add to cache for future use
                        cache.append(drug_info)
                        await PNDFScraper.save_cache(cache)
                    else:
                        # Return minimal info if not found
                        enriched.append({
                            "name": drug_name,
                            "found": False,
                            "message": "Not found in PNDF database",
                        })
                except Exception as e:
                    logger.error(f"Error enriching {drug_name}: {e}")
                    enriched.append({
                        "name": drug_name,
                        "error": str(e),
                    })

                # Respect server load
                await asyncio.sleep(PNDFScraper.REQUEST_DELAY)

        return enriched

    @staticmethod
    async def refresh_cache(drugs_to_fetch: Optional[List[str]] = None) -> None:
        """
        Refresh PNDF cache with fresh data
        If drugs_to_fetch is provided, only fetch those; otherwise fetch common drugs
        """
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
        logger.info(f"Starting PNDF cache refresh for {len(drugs)} drugs...")

        cache = await PNDFScraper.load_cache()
        cache_dict = {drug["name"].lower(): drug for drug in cache}

        for drug_name in drugs:
            if drug_name.lower() not in cache_dict:
                try:
                    drug_info = await PNDFScraper.search_drug(drug_name)
                    if drug_info:
                        cache.append(drug_info)
                        cache_dict[drug_name.lower()] = drug_info
                except Exception as e:
                    logger.error(f"Error fetching {drug_name}: {e}")

                # Respect server load
                await asyncio.sleep(PNDFScraper.REQUEST_DELAY)

        await PNDFScraper.save_cache(list(cache_dict.values()))
        logger.info(f"✓ Cache refresh complete. Total drugs: {len(cache_dict)}")

    @staticmethod
    async def cleanup():
        """Clean up browser resources (call on server shutdown)"""
        await PNDFScraper._close_browser()
        logger.info("✓ PNDF scraper cleanup complete")
