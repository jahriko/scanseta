# Hugging Face Model Deployment Guide

## Overview
Your backend has been updated to load the Qwen2.5-VL-7B-Instruct base model with your fine-tuned LoRA adapter from Hugging Face Hub: `Jahriko/prescription_model`

## What Changed

### 1. Dependencies (requirements.txt)
- Updated `transformers` to >=4.57.1
- Updated `accelerate` to >=0.33.0
- Added `peft` >=0.17.1 (for LoRA adapter support)
- Added `huggingface-hub` >=0.23.0

### 2. Backend Code (main.py)
- Added imports for `AutoProcessor`, `AutoModelForCausalLM`, and `PeftModel`
- Created `load_qwen_vl_with_lora()` function to load base model + adapter
- Updated `ModelConfig.load_model()` to accept `base_model` and `adapter_repo` parameters
- Updated `predict()` to use Qwen VL chat template with image+text inputs
- Modified startup to load from environment variables (`HF_BASE_MODEL`, `HF_ADAPTER_REPO`)
- Updated `/load-model` endpoint to accept `base_model` and `adapter_repo` query parameters

### 3. Test Client (test_client.py)
- Updated `test_load_model()` to accept base model and adapter repo parameters
- Updated example usage in comments

## Deployment Steps on Vast.ai

### Step 1: Upload Files
Upload the updated files to your Vast.ai instance:
```bash
scp -P 54052 main.py requirements.txt test_client.py root@115.231.176.132:/workspace/prescription_scanner/
```

### Step 2: Install Dependencies
SSH into your Vast.ai instance and install the updated dependencies:
```bash
ssh -p 54052 root@115.231.176.132
cd /workspace/prescription_scanner

# If using virtual environment
source venv/bin/activate

# Install/upgrade dependencies
pip install -r requirements.txt
```

### Step 3: Start the Server

**Option A: Load model on startup (recommended)**
```bash
export HF_BASE_MODEL="Qwen/Qwen2.5-VL-7B-Instruct"
export HF_ADAPTER_REPO="Jahriko/prescription_model"
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

**Option B: Start server and load model via API**
```bash
# Start server
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1

# In another terminal, load the model
curl -X POST "http://115.231.176.132:8000/load-model?base_model=Qwen/Qwen2.5-VL-7B-Instruct&adapter_repo=Jahriko/prescription_model"
```

### Step 4: Test the API

**Health Check:**
```bash
curl http://115.231.176.132:8000/health
```

**Load Model (if not loaded on startup):**
```bash
curl -X POST "http://115.231.176.132:8000/load-model?base_model=Qwen/Qwen2.5-VL-7B-Instruct&adapter_repo=Jahriko/prescription_model"
```

**Scan a Prescription:**
```bash
curl -X POST "http://115.231.176.132:8000/scan" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@prescription.jpg"
```

**Using the Test Client:**
```python
# Update test_client.py with your IP
python test_client.py
```

## API Endpoints

### GET /
Root endpoint - returns API status and whether model is loaded

### GET /health
Health check - returns status, model loaded state, device info, GPU availability

### POST /load-model
Load or reload the model
- **Parameters:**
  - `base_model` (string): Hugging Face model ID (e.g., "Qwen/Qwen2.5-VL-7B-Instruct")
  - `adapter_repo` (string): Hugging Face adapter repo (e.g., "Jahriko/prescription_model")

### POST /scan
Scan a single prescription image
- **Body:** multipart/form-data with `file` field containing image
- **Returns:** JSON with medications, raw text, processing time

### POST /scan-batch
Scan multiple prescription images
- **Body:** multipart/form-data with multiple `files`
- **Returns:** JSON array of results

## Model Loading Details

The backend now:
1. Downloads `Qwen/Qwen2.5-VL-7B-Instruct` from Hugging Face (base model)
2. Downloads your LoRA adapter from `Jahriko/prescription_model`
3. Merges the adapter with the base model using PEFT
4. Uses FP16 precision for faster inference on GPU
5. Uses `device_map="auto"` for automatic GPU memory management

## Expected Behavior

When you send a prescription image to `/scan`, the model will:
1. Process the image using Qwen VL's vision encoder
2. Apply the chat template with your custom prompt
3. Generate structured JSON output with:
   - `patient_name`
   - `doctor_name`
   - `date`
   - `medications` array with `name`, `dosage`, `frequency`

## Troubleshooting

### Model Download Issues
If the model fails to download, ensure:
- Your Vast.ai instance has internet access
- The Hugging Face Hub is accessible
- For private repos, set `HF_TOKEN` environment variable

### Out of Memory
If you run out of GPU memory:
- The model should fit on most modern GPUs with 16GB+ VRAM
- Consider using 4-bit quantization if needed (requires `bitsandbytes`)

### Slow First Request
The first request will be slower as the model downloads and loads into memory. Subsequent requests will be fast.

## Environment Variables

- `HF_BASE_MODEL`: Base model ID (default: "Qwen/Qwen2.5-VL-7B-Instruct")
- `HF_ADAPTER_REPO`: Your adapter repo (no default, must be set for auto-load)
- `HF_TOKEN`: Hugging Face token (for private repos)
- `PYTORCH_CUDA_ALLOC_CONF`: PyTorch CUDA memory config (optional)

## Next Steps

1. Test with real prescription images
2. Fine-tune the prompt in `predict()` method if needed
3. Improve `parse_prescription_text()` to better parse the JSON output
4. Add authentication for production use
5. Set up monitoring and logging
6. Consider caching the model to avoid re-downloading

## Reference

- Model on Hugging Face: https://huggingface.co/Jahriko/prescription_model
- Base Model: https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct
- PEFT Documentation: https://huggingface.co/docs/peft

