# Scanseta

Scanseta is a prescription scanning system with:
- A React + TypeScript frontend for uploading prescription images and viewing extracted data.
- A FastAPI backend for OCR extraction, medication parsing, FDA verification, and PNDF enrichment.

## Monorepo Overview

- `frontend/`: Vite + React + TypeScript application.
- `backend/`: FastAPI API and ML/scraper pipeline.
- `setup.ps1`: One-time setup script for backend + frontend.
- `dev.ps1`: Starts backend and frontend in separate PowerShell windows.

## Prerequisites

- Python 3.8+
- Node.js + npm
- Windows PowerShell (recommended for provided scripts)

## Quick Start (Windows)

From repo root:

```powershell
.\setup.ps1
.\dev.ps1
```

What this does:
- Creates `backend/.venv` (if missing)
- Installs backend requirements from `backend/requirements.txt`
- Installs Playwright Chromium for backend scrapers
- Installs frontend npm dependencies
- Creates `frontend/.env.local` with `VITE_API_BASE_URL=http://localhost:8000` (if missing)
- Launches backend on `http://localhost:8000` and frontend on Vite dev server (usually `http://localhost:5173`)

## Manual Setup

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe run_server.py
```

### Frontend

```powershell
cd frontend
npm install
Set-Content -Path .env.local -Value "VITE_API_BASE_URL=http://localhost:8000"
npm run dev
```

Optional config check:

```powershell
cd frontend
npm run check-env
```

## Configuration

### Frontend Environment Variables

- `VITE_API_BASE_URL` (required)
  - Must start with `http://` or `https://`
  - Must not end with `/`
  - Local default: `http://localhost:8000`

### Backend Environment Variables (optional)

- `HF_BASE_MODEL` (default: `Qwen/Qwen2.5-VL-7B-Instruct`)
- `HF_ADAPTER_REPO` (default: `scanseta/qwen_prescription_model`)
- `HF_HOME` (default: `./hf_home`)
- `TRANSFORMERS_CACHE` (default: `./hf_cache`)
- `HF_OFFLOAD_DIR` (default: `./offload`)
- Post-processing tuning vars used in `backend/main.py`:
  - `LEXICON_PATH`
  - `MAX_EDIT_DISTANCE`
  - `MIN_SIMILARITY`
  - `NGRAM_N`
  - `PLAUSIBILITY_THRESHOLD`
  - `MAX_CANDIDATES`
  - `MAX_LENGTH_DELTA`
  - `MIN_SIMILARITY_FOR_EDIT`
  - `AMBIGUITY_MARGIN`
- Enrichment/cache tuning:
  - `PNDF_NEGATIVE_CACHE_TTL_SECONDS`
  - `SCAN_RESULT_CACHE_TTL_SECONDS`
  - `SCAN_RESULT_CACHE_MAX_ENTRIES`

### Build Lexicon from PH Sources (via local PNDF/FDA cache)

Run from `backend/`:

```powershell
python scripts/build_drug_lexicon.py
```

Notes:
- Reads `backend/data/pndf_cache.json` + `backend/data/fda_cache.json`
- Merges optional `backend/data/drug_lexicon_overrides.txt`
- Writes `backend/data/drug_lexicon.txt`
- By default, preserves existing lexicon entries to avoid accidental shrink
- `OOV` medications are blocked from FDA/PNDF enrichment, so lexicon coverage directly affects recall
- Use `--replace-output` for strict rebuild from cache + overrides only

## API Endpoints

Base URL: `http://localhost:8000`

- `GET /` - API status summary
- `GET /health` - health status and model/device info
- `GET /model-status` - detailed model status
- `GET /load-model` - load/reload model
- `POST /scan` - scan one prescription image
- `POST /scan-batch` - scan multiple prescription images
- `POST /enrich-medications` - enrich manually provided medication names

Examples:

```powershell
curl http://localhost:8000/health
```

```powershell
curl "http://localhost:8000/load-model"
```

```powershell
curl -X POST "http://localhost:8000/enrich-medications" `
  -H "Content-Type: application/json" `
  -d "{\"drug_names\":[\"paracetamol\",\"ibuprofen\"]}"
```

```powershell
curl -X POST "http://localhost:8000/scan" `
  -F "file=@C:\path\to\prescription.jpg"
```

## Project Structure

```text
scanseta/
|- setup.ps1
|- dev.ps1
|- frontend/
|  |- package.json
|  |- .env.local (local)
|  |- src/lib/config.ts
|  `- src/lib/prescription-api.ts
`- backend/
   |- main.py
   |- run_server.py
   |- requirements.txt
   |- data/
   `- src/
      |- scrapers/
      `- post_processing/
```

## Troubleshooting

- `503 Model not loaded` on `/scan`:
  - Call `GET /load-model` first, then retry.
- Frontend cannot call backend:
  - Check `frontend/.env.local` and ensure `VITE_API_BASE_URL` is set correctly.
  - Restart frontend dev server after changing env files.
- Playwright errors during enrichment:
  - Reinstall browser: `.\.venv\Scripts\python.exe -m playwright install chromium`
- Windows async/subprocess errors with Playwright:
  - Use `python run_server.py` (it sets the Windows event loop policy correctly).

## Notes

- This project is for prescription text extraction and medication data enrichment workflows.
- Output should be reviewed by qualified professionals before clinical use.
