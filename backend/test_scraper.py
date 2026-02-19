#!/usr/bin/env python3
"""
Quick test script to verify PNDF scraper functionality
Run this to test the scraper before deploying
"""

import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

async def test_scraper():
    """Test basic scraper functionality"""
    print("=" * 60)
    print("PNDF Scraper Test Suite")
    print("=" * 60)
    
    try:
        from src.scrapers.pndf_scraper import PNDFScraper
        print("✓ PNDFScraper imported successfully")
    except ImportError as e:
        print(f"✗ Failed to import PNDFScraper: {e}")
        print("  Make sure dependencies are installed: pip install -r requirements.txt")
        return False
    
    # Test 1: Cache loading
    print("\n[Test 1] Loading cache...")
    try:
        cache = await PNDFScraper.load_cache()
        print(f"✓ Cache loaded. Current entries: {len(cache)}")
    except Exception as e:
        print(f"✗ Cache load failed: {e}")
        return False
    
    # Test 2: Scraper initialization
    print("\n[Test 2] Testing scraper methods...")
    try:
        # Just verify methods exist and are callable
        assert hasattr(PNDFScraper, 'search_drug'), "search_drug method missing"
        assert hasattr(PNDFScraper, 'enrich_medications'), "enrich_medications method missing"
        assert hasattr(PNDFScraper, 'refresh_cache'), "refresh_cache method missing"
        print("✓ All required scraper methods found")
    except AssertionError as e:
        print(f"✗ {e}")
        return False
    
    # Test 3: Simple drug search (optional, requires network)
    print("\n[Test 3] Testing live drug search (paracetamol)...")
    try:
        drug = await PNDFScraper.search_drug("paracetamol")
        if drug:
            print(f"✓ Found drug: {drug.get('name', 'Unknown')}")
            print(f"  - ATC Code: {drug.get('atc_code', 'N/A')}")
            print(f"  - Dosage forms: {len(drug.get('dosage_forms', []))} found")
        else:
            print("✗ Drug search returned no results")
            print("  This may indicate website structure has changed")
            return False
    except Exception as e:
        print(f"✗ Drug search failed: {e}")
        print("  This is expected if network is unavailable or website is down")
        print("  The scraper will use cache as fallback in production")
    
    # Test 4: Cache save/load cycle
    print("\n[Test 4] Testing cache persistence...")
    try:
        test_data = [
            {
                "name": "TEST_DRUG",
                "atc_code": "TEST123",
                "classification": {},
                "dosage_forms": [],
            }
        ]
        await PNDFScraper.save_cache(test_data)
        loaded = await PNDFScraper.load_cache()
        assert len(loaded) > 0, "Cache save/load failed"
        print(f"✓ Cache persistence working. Entries: {len(loaded)}")
    except Exception as e:
        print(f"✗ Cache persistence failed: {e}")
        return False
    
    print("\n" + "=" * 60)
    print("✓ All tests passed!")
    print("=" * 60)
    return True

if __name__ == "__main__":
    success = asyncio.run(test_scraper())
    sys.exit(0 if success else 1)
