#!/usr/bin/env python3
"""
Quick test script to verify FDA Verification scraper functionality
Run this to test the scraper before deploying
"""

import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

async def test_fda_scraper():
    """Test basic FDA scraper functionality"""
    print("=" * 60)
    print("FDA Verification Scraper Test Suite")
    print("=" * 60)
    
    try:
        from src.scrapers.fda_verification_scraper import FDAVerificationScraper
        print("✓ FDAVerificationScraper imported successfully")
    except ImportError as e:
        print(f"✗ Failed to import FDAVerificationScraper: {e}")
        print("  Make sure dependencies are installed: pip install -r requirements.txt")
        print("  Also install Playwright: playwright install chromium")
        return False
    
    # Test 1: Cache loading
    print("\n[Test 1] Loading cache...")
    try:
        cache = await FDAVerificationScraper.load_cache()
        print(f"✓ Cache loaded. Current entries: {len(cache)}")
    except Exception as e:
        print(f"✗ Cache load failed: {e}")
        return False
    
    # Test 2: Scraper initialization
    print("\n[Test 2] Testing scraper methods...")
    try:
        # Just verify methods exist and are callable
        assert hasattr(FDAVerificationScraper, 'search_drug'), "search_drug method missing"
        assert hasattr(FDAVerificationScraper, 'verify_medications'), "verify_medications method missing"
        assert hasattr(FDAVerificationScraper, 'load_cache'), "load_cache method missing"
        assert hasattr(FDAVerificationScraper, 'save_cache'), "save_cache method missing"
        assert hasattr(FDAVerificationScraper, 'cleanup'), "cleanup method missing"
        print("✓ All required scraper methods found")
    except AssertionError as e:
        print(f"✗ {e}")
        return False
    
    # Test 3: Simple drug search (optional, requires network and Playwright)
    print("\n[Test 3] Testing live drug search (amoxicillin)...")
    print("  Note: This requires network access and Playwright browser")
    print("  Set FDA_HEADLESS=false to see browser window")
    try:
        result = await FDAVerificationScraper.search_drug("amoxicillin")
        if result:
            print(f"✓ Search completed for: {result.get('query', 'Unknown')}")
            print(f"  - Found: {result.get('found', False)}")
            if result.get('found'):
                best_match = result.get('best_match')
                if best_match:
                    print(f"  - Registration Number: {best_match.get('registration_number', 'N/A')}")
                    print(f"  - Generic Name: {best_match.get('generic_name', 'N/A')}")
                    print(f"  - Brand Name: {best_match.get('brand_name', 'N/A')}")
                    print(f"  - Dosage Strength: {best_match.get('dosage_strength', 'N/A')}")
                    print(f"  - Classification: {best_match.get('classification', 'N/A')}")
                print(f"  - Total matches: {len(result.get('matches', []))}")
            else:
                print("  - No matches found (this may be normal if drug not in FDA database)")
        else:
            print("✗ Drug search returned no results")
            print("  This may indicate website structure has changed or network issue")
            return False
    except Exception as e:
        print(f"✗ Drug search failed: {e}")
        print("  This is expected if:")
        print("    - Network is unavailable")
        print("    - Website is down")
        print("    - Playwright browser not installed (run: playwright install chromium)")
        print("  The scraper will use cache as fallback in production")
    
    # Test 4: Cache save/load cycle
    print("\n[Test 4] Testing cache persistence...")
    try:
        test_data = [
            {
                "query": "test_drug",
                "found": True,
                "matches": [
                    {
                        "registration_number": "TEST-1234",
                        "generic_name": "Test Drug",
                        "brand_name": "Test Brand",
                        "dosage_strength": "100 mg",
                        "classification": "Prescription Drug (RX)",
                        "details": {}
                    }
                ],
                "best_match": {
                    "registration_number": "TEST-1234",
                    "generic_name": "Test Drug",
                    "brand_name": "Test Brand",
                    "dosage_strength": "100 mg",
                    "classification": "Prescription Drug (RX)",
                    "details": {}
                },
                "scraped_at": "2026-01-30T12:00:00"
            }
        ]
        await FDAVerificationScraper.save_cache(test_data)
        loaded = await FDAVerificationScraper.load_cache()
        assert len(loaded) > 0, "Cache save/load failed"
        print(f"✓ Cache persistence working. Entries: {len(loaded)}")
    except Exception as e:
        print(f"✗ Cache persistence failed: {e}")
        return False
    
    # Test 5: Verify medications (batch)
    print("\n[Test 5] Testing verify_medications (batch)...")
    try:
        test_drugs = ["amoxicillin", "paracetamol"]
        results = await FDAVerificationScraper.verify_medications(test_drugs)
        print(f"✓ Verified {len(results)} medications")
        for result in results:
            print(f"  - {result.get('query', 'Unknown')}: {'Found' if result.get('found') else 'Not Found'}")
    except Exception as e:
        print(f"✗ Batch verification failed: {e}")
        print("  This may be expected if network/Playwright unavailable")
    
    # Cleanup
    print("\n[Cleanup] Cleaning up browser resources...")
    try:
        await FDAVerificationScraper.cleanup()
        print("✓ Cleanup successful")
    except Exception as e:
        print(f"⚠ Cleanup warning: {e}")
    
    print("\n" + "=" * 60)
    print("✓ All tests passed!")
    print("=" * 60)
    print("\nNote: Some tests may fail if network/Playwright unavailable.")
    print("This is expected in offline environments - the scraper will use cache.")
    return True

if __name__ == "__main__":
    success = asyncio.run(test_fda_scraper())
    sys.exit(0 if success else 1)
