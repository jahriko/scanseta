# PNDF Web Scraper Integration - Implementation Guide

## Overview
This implementation adds automatic enrichment of extracted prescription medications with official data from the Philippine National Drug Formulary (https://pnf.doh.gov.ph/).

## Architecture

### New Files
- **`src/scrapers/pndf_scraper.py`** - Core scraper module with async web scraping, HTML parsing, and caching
- **`data/pndf_cache.json`** - Local JSON cache of scraped PNDF data (auto-created)

### Modified Files
- **`requirements.txt`** - Added: `beautifulsoup4`, `httpx`, `lxml`, `apscheduler`
- **`main.py`** - Added: import PNDFScraper, `/enrich-medications` endpoint, automatic enrichment in `/scan`, startup cache initialization

## Data Flow

### Original Flow
```
Prescription Image → /scan → OCR extraction → MedicationInfo[] → Response
```

### Enhanced Flow
```
Prescription Image → /scan 
  ├─→ OCR extraction → MedicationInfo[]
  └─→ Auto-enrich each drug via PNDFScraper.enrich_medications()
      ├─→ Check cache (fast)
      └─→ Live scrape if not cached (+ update cache)
      
Response includes:
  - medications: Original extraction results
  - enriched: PNDF data (classifications, dosage forms, interactions, etc.)
  - can_enrich: bool (whether enrichment is available)
```

## API Endpoints

### POST `/enrich-medications` (Manual Enrichment)
**Purpose**: Enrich a list of drug names with PNDF data on-demand

**Request**:
```json
{
  "drug_names": ["paracetamol", "ibuprofen", "amoxicillin"]
}
```

**Response**:
```json
{
  "success": true,
  "enriched_medications": [
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
      "contraindications": "Severe hepatic impairment or severe active liver disease.",
      "precautions": "WARNING: Massive overdose may cause hepatic necrosis...",
      "adverse_reactions": "Skin rash, nephrotoxicity, anemia, ...",
      "drug_interactions": "Monitor closely with: Warfarin, Phenobarbital...",
      "mechanism_of_action": "Inhibits COX-1 and COX-2...",
      "dosage_instructions": "Mild-to-moderate pain: 0.5-1g every 4-6 hours...",
      "administration": "For oral administration, may be taken with or without food...",
      "pregnancy_category": "C",
      "scraped_at": "2026-01-21T12:34:56.789123"
    }
  ],
  "count": 3
}
```

### POST `/scan` (Enhanced)
Now automatically includes enriched PNDF data

**Response Changes**:
```json
{
  "success": true,
  "medications": [...],
  "raw_text": "...",
  "processing_time": 2.34,
  "enriched": [
    {
      "name": "PARACETAMOL",
      "atc_code": "N02BE01",
      ...
    }
  ],
  "can_enrich": true
}
```

## Key Features

### 1. Async Web Scraping (`PNDFScraper.search_drug()`)
- Uses `httpx` for async HTTP requests
- Parses HTML with BeautifulSoup
- Extracts structured drug information:
  - Drug name
  - ATC code
  - Drug classifications (anatomical, therapeutic, pharmacological, chemical)
  - Dosage forms with administration routes
  - Indications, contraindications, precautions
  - Adverse reactions and drug interactions
  - Mechanism of action
  - Dosage instructions
  - Pregnancy category
  - Administration guidelines

### 2. Local Caching (`pndf_cache.json`)
- Persists across server restarts
- Populated on startup with common drugs
- Automatically updated when new drugs are found
- Fallback if live scraping fails (rate-limit/network issues)
- JSON structure: Array of drug info objects

### 3. Automatic Enrichment on `/scan`
- After OCR extraction, automatically queries PNDF
- Returns enriched data in response
- Includes `can_enrich` flag to signal frontend capability
- Errors during enrichment don't break `/scan` response

### 4. Background Cache Initialization
- On server startup, `initialize_pndf_cache()` runs asynchronously
- Refreshes cache with common medications (async, non-blocking)
- Respects server load with 500ms delays between requests
- Failures are logged but don't prevent API startup

## Configuration

### Environment Variables
No new required environment variables, but optional:
- `HF_OFFLOAD_DIR` - Cache directory for models (existing)
- `HF_HOME` - HuggingFace cache (existing)

### Rate Limiting
- `PNDFScraper.REQUEST_DELAY = 0.5` seconds between live searches
- Adjustable in `src/scrapers/pndf_scraper.py` if needed

### Cache Location
- Default: `./data/pndf_cache.json` (relative to backend root)
- Auto-creates `./data/` directory if missing

## Usage Examples

### Example 1: Automatic Enrichment (via `/scan`)
```bash
# Upload prescription image
curl -X POST -F "file=@prescription.jpg" http://localhost:8000/scan

# Response includes enriched PNDF data
{
  "success": true,
  "medications": [
    {"name": "Paracetamol", "dosage": null, "frequency": null, "confidence": 0.9}
  ],
  "enriched": [
    {
      "name": "PARACETAMOL",
      "atc_code": "N02BE01",
      "classification": {...},
      "dosage_forms": [...]
    }
  ],
  "can_enrich": true,
  "processing_time": 2.5
}
```

### Example 2: Manual Enrichment (via `/enrich-medications`)
```bash
curl -X POST http://localhost:8000/enrich-medications \
  -H "Content-Type: application/json" \
  -d '{"drug_names": ["paracetamol", "ibuprofen"]}'

# Response
{
  "success": true,
  "enriched_medications": [...],
  "count": 2
}
```

## How It Works Internally

### Search Flow
1. User uploads prescription → `/scan` endpoint
2. Model extracts drug names (e.g., "Paracetamol")
3. `PNDFScraper.enrich_medications()` called with drug names
4. For each drug:
   - Check local cache (`pndf_cache.json`)
   - If not cached: `search_drug()` queries `pnf.doh.gov.ph`
   - `_parse_drug_page()` extracts structured data with regex/BeautifulSoup
   - Update cache for future use
5. Return enriched data in `/scan` response

### Parsing Strategy
- Uses regex to extract structured sections from HTML
- Patterns match:
  - ATC code: `ATC Code[:\s]+([A-Z]\d{2}[A-Z]{2}\d{2})`
  - Dosage forms: `(ORAL|RECTAL|IM|IV|...) › form (status)`
  - Section headers: "Indications", "Contraindications", etc.
- Falls back gracefully if parsing fails

### Cache Strategy
- **On startup**: Refresh common drugs (async, non-blocking)
- **On search**: Check cache first (fast), then live search (slow)
- **On enrichment success**: Auto-save to cache
- **On network failure**: Use stale cache data

## Frontend Integration

### Expected Behavior
The frontend **should**:
1. Call `/scan` and receive enriched data automatically
2. Display enriched PNDF information on results screen
3. Check `can_enrich` flag to show/hide enrichment UI
4. Optionally call `/enrich-medications` for manual lookup

### Response Structure for Frontend
- `medications`: Original OCR extraction (name, dosage, frequency, confidence)
- `enriched`: PNDF data with classifications, interactions, warnings
- `can_enrich`: Boolean indicating if enrichment succeeded

## Troubleshooting

### Cache Not Updating
```bash
# Check cache file exists
ls -la ./data/pndf_cache.json

# Clear cache and restart server (will re-populate on startup)
rm ./data/pndf_cache.json
# Server restart triggers initialize_pndf_cache()
```

### Scraper Not Finding Drugs
1. Verify website structure: Visit `https://pnf.doh.gov.ph/`
2. HTML parsing may need adjustment if site HTML changes
3. Check logs: `[ERROR] Error searching for {drug_name}:`
4. Website may be down → scraper falls back to cache

### Performance Issues
- First request is slower (model + scraper loading)
- Subsequent requests faster (cache hits)
- If too many live scrapes: Increase `REQUEST_DELAY`
- Monitor server load during cache initialization

## Future Enhancements

1. **Scheduled cache refresh**: Use APScheduler for daily updates
2. **Database integration**: Store PNDF data in PostgreSQL instead of JSON
3. **Fuzzy matching**: Handle drug name variations (e.g., "paracetamol" vs "acetaminophen")
4. **Drug interaction warnings**: Parse interactions and surface dangerous combinations
5. **API for PNDF**: Expose `/pndf-search` endpoint for direct searches
6. **Cron job**: Periodic cache refresh via external scheduler

## Files Modified/Created

### New
```
src/
├── __init__.py
└── scrapers/
    ├── __init__.py
    └── pndf_scraper.py          (310 lines - core scraper)
data/
└── pndf_cache.json              (auto-generated)
```

### Modified
```
requirements.txt                 (added 4 dependencies)
main.py                          (added imports, endpoints, startup task)
```

## Dependencies

- **beautifulsoup4** - HTML parsing
- **httpx** - Async HTTP client
- **lxml** - HTML parser backend
- **apscheduler** - Scheduled tasks (optional, prepared for future use)

All dependencies are optional from the model's perspective; scraper gracefully handles missing data.
