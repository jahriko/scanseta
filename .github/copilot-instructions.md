# Scanseta Backend - AI Agent Instructions

## Project Overview
**Scanseta Backend** is a FastAPI server that processes prescription images using a fine-tuned Qwen2.5-VL multimodal AI model. The system is optimized for high-contrast prescription extraction with OCR metrics (WER, accuracy) and CPU fallback support.

**Core Flow**: Image upload → OCR pipeline preprocessing → Vision model inference → Medication extraction → Returns structured JSON with confidence scores.

## Architecture

### Entry Points
- **[main.py](main.py)** (312 lines): FastAPI app, model loading, inference endpoints
- **[pipeline.py](pipeline.py)** (607 lines): Optimized OCR preprocessing, model inference wrapper with metrics

### Key Components

#### Model System
- **Base Model**: `Qwen/Qwen2.5-VL-7B-Instruct` (7B multimodal Vision-Language model)
- **LoRA Adapter**: `Jahriko/prescription_model` (fine-tuned for prescription OCR)
- **Device Handling**: Automatically uses CUDA if available, falls back to CPU with FP32 precision
- **Model Config Class** ([main.py](main.py#L70-L85)): Singleton-like pattern managing model/processor state

#### Pipeline Processing
- **Image Preprocessing**: High-contrast enhancement, deskewing, noise reduction (CV2 operations)
- **Vision Input**: Qwen VL chat template via `process_vision_info` from `qwen_vl_utils`
- **Metrics**: Optional WER (Word Error Rate) calculation via `jiwer` library if ground truth available

### Dependencies
Key packages in [requirements.txt](requirements.txt):
- `fastapi`, `uvicorn` - Web server
- `transformers`, `torch` - Model inference
- `peft` - LoRA adapter loading
- `pillow`, `opencv-python-headless` - Image processing
- `qwen-vl-utils` - Qwen-specific vision preprocessing

## Critical Patterns

### FastAPI Structure
1. **CORS Middleware** ([main.py](main.py#L24-L30)): Allows all origins (adjust for production)
2. **Response Models**: Pydantic `BaseModel` defines API contracts (`MedicationInfo`, `PrescriptionResponse`)
3. **Error Handling**: HTTPException with detail messages; errors logged to stdout

### Model Loading
- Lazy-loaded on first request to `/load-model`
- Parameters passed as query strings: `?base_model=...&adapter_repo=...`
- LoRA adapter is optional; base model works alone if `adapter_repo=None`

### Inference Pattern
**`ModelConfig.predict(image)`**:
1. Import `process_vision_info` from `qwen_vl_utils`
2. Build chat message with image and prompt (fixed: "Extract medication info")
3. Call `model.chat(...)` with chat template
4. Parse response text into structured medications
5. Return dict with success, medications list, timing

### Medication Extraction
- Model outputs unstructured text; backend parses for: medication name, dosage, frequency
- Fallback: If parsing fails, return medications with placeholder info
- Confidence scores come from model output or default to 0.8

### OCR Metrics (Optional)
- [pipeline.py](pipeline.py#L40-L60) includes `OCRMetrics` class for WER calculation
- Requires ground truth text for comparison
- Not used in production API; for evaluation only

## API Endpoints

### `GET /health`
Returns model status, device (cuda/cpu), model loaded flag.
```
{
  "message": "Prescription Scanner API is running",
  "status": "ok",
  "model_loaded": true,
  "device": "cuda",
  "cuda_available": true
}
```

### `POST /load-model`
Query params: `base_model`, `adapter_repo` (optional)
Loads model and LoRA adapter into `ModelConfig.model`; returns success message.

### `POST /scan`
Form data: `file` (image)
Runs inference; returns:
```json
{
  "success": true,
  "medications": [
    { "name": "Aspirin", "dosage": "500mg", "frequency": "daily", "confidence": 0.92 }
  ],
  "raw_text": "...",
  "doctor_name": "...",
  "patient_name": "...",
  "date": "...",
  "processing_time": 2.34
}
```

## Development Workflow

### Setup
```bash
python -m venv venv
source venv/bin/activate      # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Running Locally
```bash
python main.py                 # Runs on http://localhost:8000
# Or
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### GPU/CUDA Setup
- Requires `torch` with CUDA support (check: `python -c "import torch; print(torch.cuda.is_available())"`)
- For CPU-only: Force `torch.float32` in [main.py](main.py#L60) (already implemented)
- First inference takes ~2-5s for model load; subsequent are ~1-2s

### Testing Endpoints
```bash
# Health check
curl http://localhost:8000/health

# Load model
curl -X POST "http://localhost:8000/load-model?base_model=Qwen/Qwen2.5-VL-7B-Instruct&adapter_repo=Jahriko/prescription_model"

# Scan image
curl -X POST -F "file=@prescription.jpg" http://localhost:8000/scan
```

## Common Tasks

### Changing Model/Adapter
Edit the default parameters passed from frontend ([frontend prescription-api.ts](../scanseta-2-frontend/src/lib/prescription-api.ts#L66-L68)):
- Base model ID: `Qwen/Qwen2.5-VL-7B-Instruct`
- Adapter repo: `Jahriko/prescription_model`

To use different adapter: Frontend sends new `adapter_repo` query param to `/load-model`.

### Adding Medication Parsing Logic
1. Model outputs text in `model.chat()` response
2. Parsing happens in [pipeline.py](pipeline.py) `extract_medications()` or inline in [main.py](main.py#L110-L130)
3. Current approach: Regex/string parsing; consider NER for production

### Deployment (Vast.ai Example)
See [DEPLOYMENT.md](DEPLOYMENT.md):
1. SSH to instance
2. Upload files via SCP or git clone
3. Create venv, install deps
4. Run `python main.py` on exposed port 8000
5. Frontend connects via backend URL (Vast.ai public IP:8000)

### HuggingFace Hub Integration
- Models auto-downloaded from HF Hub on first load
- Cache location: `~/.cache/huggingface/hub/`
- For offline: Pre-download models and set `HF_HOME` env var

## Logging & Debugging
- Logger configured at module level: `logger = logging.getLogger(__name__)`
- All model loading/inference steps logged to stdout
- Device info logged on startup
- Errors logged before HTTPException raise

## Production Considerations
- **CORS**: Currently `allow_origins=["*"]`; restrict to frontend domain before deploy
- **GPU Memory**: 7B model ~15GB VRAM (use smaller model if constrained)
- **Model Caching**: Load once, reuse across requests (singleton pattern in `ModelConfig`)
- **Timeouts**: Add request timeout in production (currently unlimited)

## Git & Version Control
- [requirements.txt](requirements.txt) pinned versions (reproducible builds)
- [start_server.sh](start_server.sh) included for shell-based deployment
- No virtual env tracked in git (add `venv/` to `.gitignore` if missing)
