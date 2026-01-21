# PNDF Web Scraper Implementation - Summary

## ✓ Implementation Complete

The Scanseta backend now includes automatic enrichment of extracted prescription medications with official data from the Philippine National Drug Formulary (https://pnf.doh.gov.ph/).

---

## What Was Added

### 1. **New Scraper Module** (`src/scrapers/pndf_scraper.py`)
- 310 lines of async Python code
- Core class: `PNDFScraper` with methods:
  - `search_drug(drug_name)` - Query PNDF website, parse HTML
  - `enrich_medications(drug_names)` - Batch enrichment with cache fallback
  - `load_cache()` / `save_cache()` - JSON persistence
  - `refresh_cache()` - Background cache refresh
  - `_parse_drug_page()` - HTML parsing with BeautifulSoup + regex

- **Extracts**:
  - Drug name, ATC code
  - Classifications (anatomical, therapeutic, pharmacological, chemical)
  - Dosage forms with administration routes (ORAL, RECTAL, IM, IV, etc.)
  - Indications, contraindications, precautions
  - Adverse reactions, drug interactions
  - Mechanism of action, dosage instructions, pregnancy category

### 2. **New Endpoints** (in `main.py`)
#### `POST /enrich-medications`
Manual drug enrichment endpoint. Request:
```json
{"drug_names": ["paracetamol", "ibuprofen"]}
```
Returns PNDF data with classifications, interactions, dosages, etc.

### 3. **Enhanced `/scan` Endpoint**
Now automatically enriches extracted medications. Response includes:
- `medications`: Original OCR results
- `enriched`: PNDF data for each drug
- `can_enrich`: Boolean flag

### 4. **Startup Initialization**
- `initialize_pndf_cache()` - Background task that runs on server startup
- Refreshes cache with common medications asynchronously (non-blocking)
- Respects server load (500ms delays between requests)

### 5. **Local Caching**
- File: `data/pndf_cache.json`
- Persists across server restarts
- Auto-created directory
- Fallback when network unavailable

### 6. **Dependencies Added** (requirements.txt)
```
beautifulsoup4==4.12.2   # HTML parsing
httpx==0.25.1            # Async HTTP client
lxml==5.0.1              # Fast HTML parser
apscheduler==3.10.4      # For future scheduled tasks
```

---

## Architecture

```
Frontend: /scan → Backend: POST /scan
                     ↓
                  Model OCR extracts drug names
                     ↓
                  Auto-call PNDFScraper.enrich_medications()
                     ↓
              Check cache (fast) → Found: Return cached data
                     ↓ (Not found)
              Live scrape (slow) → Update cache
                     ↓
          Return enriched data in /scan response
```

---

## Key Features

✅ **Automatic Enrichment**: After OCR, medicines are automatically enriched with official PNDF data  
✅ **Async/Non-blocking**: Cache refresh doesn't block server startup  
✅ **Intelligent Caching**: First request slower, subsequent requests fast (cache hits)  
✅ **Graceful Degradation**: Errors don't break `/scan` - just returns non-enriched data  
✅ **Rate Limiting**: 500ms delays between requests to respect PNDF server  
✅ **BeautifulSoup Parsing**: Simple HTML extraction (no JavaScript rendering needed)  
✅ **Separate Endpoint**: `/enrich-medications` for manual lookups  
✅ **Production-Ready**: Error logging, proper async patterns, Pydantic validation  

---

## Data Flow Example

### Step 1: User Uploads Prescription
```bash
curl -X POST -F "file=@prescription.jpg" http://localhost:8000/scan
```

### Step 2: Backend Processing
1. Model extracts: `["Paracetamol", "Ibuprofen"]`
2. Calls: `PNDFScraper.enrich_medications(["Paracetamol", "Ibuprofen"])`
3. For each drug:
   - Check `data/pndf_cache.json`
   - If not found: Query `pnf.doh.gov.ph`, parse HTML, cache result
   - Wait 500ms (rate limiting)

### Step 3: Response
```json
{
  "success": true,
  "medications": [
    {"name": "Paracetamol", "dosage": null, "frequency": null, "confidence": 0.9}
  ],
  "enriched": [
    {
      "name": "PARACETAMOL",
      "atc_code": "N02BE01",
      "classification": {
        "anatomical": "Nervous System",
        "therapeutic": "Analgesics",
        "pharmacological": "Other Analgesics and Antipyretics",
        "chemical_class": "Non-Opioid Analgesics"
      },
      "dosage_forms": [
        {"route": "ORAL", "form": "300 mg tablet", "status": "OTC"},
        {"route": "ORAL", "form": "500 mg tablet", "status": "OTC"},
        ...
      ],
      "indications": "Management of mild-moderate pain, fever.",
      "contraindications": "Severe hepatic impairment...",
      "precautions": "WARNING: Massive overdose may cause hepatic necrosis...",
      "adverse_reactions": "Skin rash, nephrotoxicity, anemia...",
      "drug_interactions": "Monitor closely with: Warfarin, Phenobarbital...",
      "mechanism_of_action": "Inhibits COX-1 and COX-2...",
      "dosage_instructions": "0.5-1g every 4-6 hours (maximum 4g daily)...",
      "administration": "For oral administration, may be taken with or without food...",
      "pregnancy_category": "C",
      "scraped_at": "2026-01-21T12:34:56.789123"
    }
  ],
  "can_enrich": true,
  "processing_time": 2.5
}
```

---

## File Structure

```
scanseta-2-backend/
├── main.py                    (MODIFIED - added imports, endpoints, startup)
├── requirements.txt           (MODIFIED - added 4 dependencies)
├── PNDF_SCRAPER_GUIDE.md     (NEW - detailed documentation)
├── test_scraper.py           (NEW - validation script)
├── src/
│   ├── __init__.py           (NEW)
│   └── scrapers/
│       ├── __init__.py       (NEW)
│       └── pndf_scraper.py   (NEW - 310 lines, core scraper)
└── data/
    └── pndf_cache.json       (AUTO-GENERATED - JSON cache)
```

---

## How to Deploy

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Start Server
```bash
python main.py
# or
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Test Scraper (Optional)
```bash
python test_scraper.py
```

### 4. First Request
- Cache initialization runs in background on startup
- First `/scan` request may take 2-5s (model + scraper loading)
- Subsequent requests faster (~1-2s, cache hits)

---

## API Usage

### Auto-Enrichment (Built-in)
```bash
# Just call /scan as normal - enrichment happens automatically
curl -X POST -F "file=@prescription.jpg" http://localhost:8000/scan
```

### Manual Enrichment
```bash
# Query specific drugs
curl -X POST http://localhost:8000/enrich-medications \
  -H "Content-Type: application/json" \
  -d '{"drug_names": ["paracetamol", "ibuprofen", "amoxicillin"]}'
```

---

## Frontend Integration (Recommended)

The frontend should:

1. **Display enriched data on results screen**:
   - Show PNDF classifications (ATC, anatomical, therapeutic)
   - Display available dosage forms
   - Show warnings (contraindications, precautions)
   - List drug interactions

2. **Check `can_enrich` flag**:
   - Only show enrichment section if `true`
   - Handle cases where enrichment wasn't available

3. **Optional: Manual lookup**
   - Add "View in PNDF" button calling `/enrich-medications`
   - Show detailed drug information in modal/new screen

---

## Troubleshooting

### Dependencies Not Installed
```bash
# Install missing packages
pip install beautifulsoup4 httpx lxml apscheduler
```

### Cache Issues
```bash
# Clear cache (will re-populate on next startup)
rm data/pndf_cache.json

# Restart server
# Cache initialization will fetch common drugs again
```

### Scraper Not Finding Drugs
- Website HTML structure may have changed
- Regex patterns in `_parse_drug_page()` may need adjustment
- See `PNDF_SCRAPER_GUIDE.md` for HTML structure details

### Performance
- First request slower (initialization)
- Enable cache hits: `data/pndf_cache.json` should grow over time
- If too many network calls: Check `REQUEST_DELAY` in scraper

### Network/Server Down
- Scraper falls back to cache automatically
- Check logs: `[WARNING] Could not refresh PNDF...`
- Old cached data is used instead of failing

---

## Testing

### Run Validation Script
```bash
python test_scraper.py
```

Output:
```
============================================================
PNDF Scraper Test Suite
============================================================
✓ PNDFScraper imported successfully

[Test 1] Loading cache...
✓ Cache loaded. Current entries: 10

[Test 2] Testing scraper methods...
✓ All required scraper methods found

[Test 3] Testing live drug search (paracetamol)...
✓ Found drug: PARACETAMOL
  - ATC Code: N02BE01
  - Dosage forms: 12 found

[Test 4] Testing cache persistence...
✓ Cache persistence working. Entries: 11

============================================================
✓ All tests passed!
============================================================
```

---

## Future Enhancements

- **Scheduled cache refresh**: Use APScheduler for daily updates
- **Drug interaction warnings**: Alert on dangerous drug combinations
- **Fuzzy matching**: Handle name variations ("paracetamol" vs "acetaminophen")
- **Database backend**: PostgreSQL instead of JSON for large datasets
- **API search endpoint**: Public `/pndf-search` for direct lookups
- **Offline mode**: Bundle static PNDF data with app

---

## Configuration

### Optional Environment Variables
```bash
# Existing (still used)
HF_BASE_MODEL=Qwen/Qwen2.5-VL-7B-Instruct
HF_ADAPTER_REPO=Jahriko/prescription_model

# Scraper (defaults work fine)
# No new required env vars
```

### Tuning
In `src/scrapers/pndf_scraper.py`:
- `REQUEST_DELAY = 0.5` - Increase if server requests too fast
- `refresh_cache()` - Modify `default_drugs` list for different initial cache

---

## Files Modified

### main.py
- Added: `from src.scrapers.pndf_scraper import PNDFScraper`
- Added: `import asyncio`
- Added: `EnrichmentRequest` Pydantic model
- Modified: `PrescriptionResponse` (added `enriched`, `can_enrich`)
- Added: `initialize_pndf_cache()` function
- Modified: `startup_event()` (now calls cache init)
- Added: `POST /enrich-medications` endpoint
- Modified: `POST /scan` (now auto-enriches medications)

### requirements.txt
- Added: `beautifulsoup4==4.12.2`
- Added: `httpx==0.25.1`
- Added: `lxml==5.0.1`
- Added: `apscheduler==3.10.4`

---

## Documentation

- [PNDF_SCRAPER_GUIDE.md](./PNDF_SCRAPER_GUIDE.md) - Detailed technical documentation
- [test_scraper.py](./test_scraper.py) - Validation and testing script
- This file - High-level summary

---

## Support

For issues or questions:
1. Check logs: `[ERROR]`, `[WARNING]` in console output
2. See `PNDF_SCRAPER_GUIDE.md` troubleshooting section
3. Verify dependencies: `pip list | grep -E "beautifulsoup|httpx|lxml"`
4. Test with: `python test_scraper.py`

---

## Notes

✅ All syntax checked and valid  
✅ Follows FastAPI async patterns  
✅ Graceful error handling  
✅ Non-blocking startup  
✅ Cache-first approach for performance  
✅ Production-ready logging  
✅ Ready for deployment
