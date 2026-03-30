"""
Philippine National Drug Formulary (PNDF) Web Scraper
Fetches and parses medication information from https://pnf.doh.gov.ph/

Uses patchright (anti-detection Playwright fork) with headless=False to bypass
Cloudflare WAF. The browser window is positioned off-screen so it is invisible
to the user while still passing CF bot-detection checks.
"""

import asyncio
import json
import logging
import os
import re
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

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


def _scrape_drug_sync(drug_name: str) -> List[Dict]:
    """Launch patchright off-screen, search for drug_name, expand all accordion results."""
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
            logger.info(f"[pndf] Loading {FRONTEND_URL} ...")
            page.goto(FRONTEND_URL, wait_until="networkidle", timeout=TIMEOUT)
            logger.info(f"[pndf] Page loaded: {page.title()}")

            # Dismiss disclaimer modal
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
            except Exception:
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)

            # Type drug name — only keyboard.type triggers React debounced search
            logger.info(f"[pndf] Searching for '{drug_name}' ...")
            search_input = page.locator("#inputGlobalSearch")
            search_input.wait_for(state="visible", timeout=10_000)
            search_input.click()
            page.keyboard.type(drug_name, delay=100)

            # Poll for API response
            for _ in range(20):
                page.wait_for_timeout(1_000)
                if search_data["body"] is not None:
                    break

            if search_data["body"] is None:
                logger.warning(f"[pndf] No search response for '{drug_name}'.")
                return []

            drug_ids = _extract_drug_list(search_data["body"])
            logger.info(f"[pndf] {len(drug_ids)} result(s) found.")
            if not drug_ids:
                return []

            try:
                page.wait_for_selector("div.w-full.group > button", state="visible", timeout=30_000)
            except Exception:
                logger.warning("[pndf] Result buttons not found. Returning IDs only.")
                return drug_ids

            try:
                page.wait_for_selector("text=Syncing pharmacopoeia data", state="hidden", timeout=60_000)
            except Exception:
                pass

            results = []
            item_groups = page.locator("div.w-full.group")
            count = item_groups.count()
            logger.info(f"[pndf] Expanding {count} item(s) ...")

            for i in range(count):
                group = item_groups.nth(i)
                btn = group.locator("button").first
                drug_name_text = btn.locator("h3").inner_text().strip()

                btn.click()
                detail_selector = "div.px-4.py-4"
                try:
                    group.locator(detail_selector).wait_for(state="visible", timeout=15_000)
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
    details: Dict = raw.get("details", {})

    def get(*keys: str) -> Optional[str]:
        for k in keys:
            for dk, dv in details.items():
                if dk.strip().lower() == k.lower() and dv:
                    return dv
        return None

    raw_dosage = get("Dosage Form(s)", "Dosage Forms", "Dosage Form")
    dosage_forms = []
    if raw_dosage:
        for part in raw_dosage.split(","):
            part = part.strip()
            if part:
                dosage_forms.append({"form": part})

    atc_raw = get("ATC Code", "ATC")
    atc_code = None
    if atc_raw:
        m = re.search(r"[A-Z]\d{2}[A-Z]{2}\d{2}", atc_raw)
        atc_code = m.group(0) if m else atc_raw.strip()

    classification = {
        "anatomical": get("Anatomical"),
        "therapeutic": get("Therapeutic"),
        "pharmacological": get("Pharmacological"),
        "chemical_class": get("Chemical Class"),
    }
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
        "adverse_reactions": get("Adverse Drug Reactions", "Adverse Reactions", "Adverse Effects"),
        "drug_interactions": get("Drug Interactions", "Drug Interaction"),
        "mechanism_of_action": get("Mechanism of Action", "Mechanism"),
        "dosage_instructions": get("Dosage", "Dosage Instructions", "Dosing"),
        "administration": get("Administration", "Route of Administration"),
        "pregnancy_category": get("Pregnancy Category", "Pregnancy"),
        "scraped_at": datetime.now().isoformat(),
    }


class PNDFScraper:
    REQUEST_DELAY = 0.5
    CACHE_TTL_SECONDS = int(os.getenv("PNDF_CACHE_TTL_SECONDS", "0"))

    @staticmethod
    def _cache_key(entry: Dict) -> Optional[str]:
        return entry.get("name")

    @staticmethod
    async def search_drug(drug_name: str) -> Optional[Dict]:
        if not PATCHRIGHT_AVAILABLE:
            logger.error("patchright not installed. Run: pip install patchright && patchright install chromium")
            return None
        try:
            loop = asyncio.get_event_loop()
            raw_results: List[Dict] = await loop.run_in_executor(None, _scrape_drug_sync, drug_name)
        except Exception as exc:
            logger.error(f"[pndf] Error scraping '{drug_name}': {exc}")
            return None
        if not raw_results:
            return None
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
    async def enrich_medications(drug_names: List[str], cache: Optional[List[Dict]] = None) -> List[Dict]:
        if cache is None:
            cache = await PNDFScraper.load_cache()

        cache_dict = {
            normalize_key(drug.get("name", "")): drug
            for drug in cache
            if normalize_key(drug.get("name", ""))
        }

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
                        cache = await upsert_cache_entry(CACHE_PATH, drug_info, key_fn=PNDFScraper._cache_key)
                        cache_dict[key] = drug_info
                    else:
                        error_code = "patchright_unavailable" if not PATCHRIGHT_AVAILABLE else "not_found"
                        enriched.append({
                            "name": drug_name,
                            "found": False,
                            "message": "Scraper runtime unavailable" if error_code == "patchright_unavailable" else "Not found in PNDF database",
                            "error_code": error_code,
                        })
                except Exception as exc:
                    logger.error(f"[pndf] Error enriching '{drug_name}': {exc}")
                    enriched.append({"name": drug_name, "found": False, "error": str(exc), "error_code": "scrape_error"})

                await asyncio.sleep(PNDFScraper.REQUEST_DELAY)

        return enriched

    @staticmethod
    async def refresh_cache(drugs_to_fetch: Optional[List[str]] = None) -> None:
        default_drugs = ["paracetamol", "ibuprofen", "aspirin", "amoxicillin", "metformin",
                         "lisinopril", "atorvastatin", "omeprazole", "loratadine", "cetirizine"]
        drugs = drugs_to_fetch or default_drugs
        logger.info(f"[pndf] Starting cache refresh for {len(drugs)} drugs ...")

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
                        cache = await upsert_cache_entry(CACHE_PATH, drug_info, key_fn=PNDFScraper._cache_key)
                        cache_dict[normalize_key(drug_name)] = drug_info
                except Exception as exc:
                    logger.error(f"[pndf] Error refreshing '{drug_name}': {exc}")
                await asyncio.sleep(PNDFScraper.REQUEST_DELAY)

        logger.info(f"[pndf] Cache refresh complete. Total: {len(cache_dict)} drugs.")

    @staticmethod
    async def cleanup():
        logger.info("[pndf] PNDF scraper cleanup complete (nothing to close).")
