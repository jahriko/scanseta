"""
Philippine National Drug Formulary (PNDF) Web Scraper
Fetches and parses medication information from https://pnf.doh.gov.ph/
"""

import httpx
import json
import logging
import asyncio
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
from bs4 import BeautifulSoup
import re

logger = logging.getLogger(__name__)

CACHE_DIR = Path("./data")
CACHE_PATH = CACHE_DIR / "pndf_cache.json"
PNDF_BASE_URL = "https://pnf.doh.gov.ph"


class PNDFScraper:
    """Scraper for Philippine National Drug Formulary"""

    # Request delay (ms) between searches to respect server
    REQUEST_DELAY = 0.5

    @staticmethod
    async def search_drug(drug_name: str) -> Optional[Dict]:
        """
        Search for a drug on PNDF website and parse the results
        
        Returns dict with drug information or None if not found
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Try to fetch search results
                # PNDF search likely uses a POST or specific endpoint
                search_url = f"{PNDF_BASE_URL}/"
                
                params = {
                    "q": drug_name,
                    "searchtype": "drug",  # Adjust based on actual site structure
                }

                logger.info(f"Searching PNDF for: {drug_name}")
                
                # Try GET request first
                response = await client.get(search_url, params=params)
                response.raise_for_status()

                # Parse HTML response
                soup = BeautifulSoup(response.text, "lxml")

                # Extract drug information from parsed HTML
                drug_info = PNDFScraper._parse_drug_page(soup, drug_name)

                if drug_info:
                    logger.info(f"✓ Found drug: {drug_name}")
                    return drug_info
                else:
                    logger.info(f"✗ Drug not found: {drug_name}")
                    return None

        except httpx.HTTPError as e:
            logger.error(f"HTTP error searching for {drug_name}: {e}")
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
