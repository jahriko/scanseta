"""
Philippine National Drug Formulary (PNDF) Web Scraper
Fetches and parses medication information from https://pnf.doh.gov.ph/
Uses Playwright to handle JavaScript-rendered content (Next.js with Radix dialogs)
"""

import json
import logging
import asyncio
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


class PNDFScraper:
    """Scraper for Philippine National Drug Formulary using Playwright for JS-rendered content"""

    # Request delay (seconds) between searches to respect server
    REQUEST_DELAY = 0.5
    
    # Shared browser instance (initialized lazily)
    _browser: Optional[Browser] = None
    _playwright_context = None

    @staticmethod
    async def _get_browser() -> Browser:
        """Get or create a shared browser instance"""
        if PNDFScraper._browser is None:
            if not PLAYWRIGHT_AVAILABLE:
                raise RuntimeError("Playwright not installed. Run: pip install playwright && playwright install chromium")
            
            playwright = await async_playwright().start()
            PNDFScraper._playwright_context = playwright
            PNDFScraper._browser = await playwright.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox']  # For server environments
            )
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
        Handle Radix dialog that appears on page refresh
        Looks for common dialog close buttons/selectors
        """
        try:
            # Wait a bit for dialog to appear
            await page.wait_for_timeout(500)
            
            # Common Radix dialog close button selectors
            dialog_selectors = [
                'button[aria-label="Close"]',
                'button[data-radix-dialog-close]',
                '[role="dialog"] button:has-text("Close")',
                '[role="dialog"] button:has-text("×")',
                'button:has-text("Dismiss")',
                '[data-radix-portal] button',
                # Generic dialog overlay close
                'button[class*="close"]',
                'button[class*="Close"]',
            ]
            
            for selector in dialog_selectors:
                try:
                    close_button = page.locator(selector).first
                    if await close_button.is_visible(timeout=1000):
                        logger.info(f"Found dialog close button: {selector}")
                        await close_button.click()
                        await page.wait_for_timeout(300)  # Wait for dialog to close
                        logger.info("✓ Dialog closed")
                        return
                except PlaywrightTimeoutError:
                    continue
            
            logger.debug("No Radix dialog found (or already closed)")
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

        try:
            browser = await PNDFScraper._get_browser()
            page = await browser.new_page()
            
            logger.info(f"Searching PNDF for: {drug_name}")
            
            # Navigate to the site
            await page.goto(PNDF_BASE_URL, wait_until="networkidle", timeout=30000)
            
            # Handle Radix dialog that appears on refresh
            await PNDFScraper._handle_radix_dialog(page)
            
            # Try to find and interact with search functionality
            # Common search selectors for Next.js apps
            search_selectors = [
                'input[type="search"]',
                'input[placeholder*="Search"]',
                'input[placeholder*="search"]',
                'input[name="search"]',
                'input[name="q"]',
                'input[class*="search"]',
                '[data-testid="search"]',
            ]
            
            search_input = None
            for selector in search_selectors:
                try:
                    search_input = page.locator(selector).first
                    if await search_input.is_visible(timeout=2000):
                        logger.info(f"Found search input: {selector}")
                        break
                except PlaywrightTimeoutError:
                    continue
            
            if not search_input:
                logger.warning("Could not find search input. Attempting to parse current page...")
            else:
                # Type drug name in search
                await search_input.fill(drug_name)
                await page.wait_for_timeout(500)
                
                # Try to submit search (look for submit button or press Enter)
                submit_selectors = [
                    'button[type="submit"]',
                    'button:has-text("Search")',
                    'button[aria-label*="Search"]',
                    '[data-testid="search-submit"]',
                ]
                
                submitted = False
                for selector in submit_selectors:
                    try:
                        submit_button = page.locator(selector).first
                        if await submit_button.is_visible(timeout=1000):
                            await submit_button.click()
                            submitted = True
                            break
                    except PlaywrightTimeoutError:
                        continue
                
                if not submitted:
                    # Try pressing Enter on search input
                    await search_input.press("Enter")
                    submitted = True
                
                # Wait for results to load (common result container selectors)
                try:
                    await page.wait_for_selector(
                        '[class*="result"], [class*="Result"], [data-testid*="result"], article, main',
                        timeout=10000
                    )
                    await page.wait_for_timeout(1000)  # Extra wait for dynamic content
                except PlaywrightTimeoutError:
                    logger.warning("Results may not have loaded, proceeding anyway...")
            
            # Get page HTML after JavaScript execution
            html_content = await page.content()
            
            # Close the page
            await page.close()
            
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
