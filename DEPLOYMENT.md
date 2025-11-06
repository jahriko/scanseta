# Prescription Scanner Backend - Deployment Guide

## Step 1: Connect to Your Vast.ai Instance

```bash
ssh -p 54052 root@115.231.176.132
```

## Step 2: Upload Files to Your Instance

From your local machine, upload the files:

```bash
# Upload all project files
scp -P 54052 main.py root@115.231.176.132:/workspace/prescription_scanner/
scp -P 54052 requirements.txt root@115.231.176.132:/workspace/prescription_scanner/
scp -P 54052 setup_prescription_backend.sh root@115.231.176.132:/workspace/prescription_scanner/
scp -P 54052 start_server.sh root@115.231.176.132:/workspace/prescription_scanner/
```

Or use git:
```bash
# Clone your repository
cd /workspace
git clone your-repo-url prescription_scanner
cd prescription_scanner
```

## Step 3: Run Setup Script

```bash
cd /workspace/prescription_scanner
chmod +x setup_prescription_backend.sh
./setup_prescription_backend.sh
```

## Step 4: Install Dependencies

```bash
source venv/bin/activate
pip install -r requirements.txt
```

## Step 5: Upload Your Fine-tuned Model

Create a models directory and upload your model:

```bash
mkdir -p /workspace/models/prescription_scanner_model
```

Then from your local machine:
```bash
scp -P 54052 -r /path/to/your/model/* root@115.231.176.132:/workspace/models/prescription_scanner_model/
```

Or use HuggingFace Hub:
```python
from transformers import AutoModel, AutoProcessor

model_name = "your-username/your-model-name"
model = AutoModel.from_pretrained(model_name)
processor = AutoProcessor.from_pretrained(model_name)

model.save_pretrained("/workspace/models/prescription_scanner_model")
processor.save_pretrained("/workspace/models/prescription_scanner_model")
```

## Step 6: Update Model Path in main.py

Edit the MODEL_PATH in main.py (line ~98):

```python
MODEL_PATH = "/workspace/models/prescription_scanner_model"
```

## Step 7: Configure Vast.ai Port Forwarding

Your FastAPI server will run on port 8000. Make sure this port is exposed:

1. Go to your Vast.ai dashboard
2. Find your instance (ID: 27565843)
3. Check that port 8000 is in the exposed port range (53988-54038)
4. You'll access it via: http://115.231.176.132:[mapped_port]

## Step 8: Start the Server

```bash
chmod +x start_server.sh
./start_server.sh
```

Or manually:
```bash
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

## Step 9: Test the API

From another terminal on your local machine:

```bash
# Health check
curl http://115.231.176.132:8000/health

# Test with an image
curl -X POST "http://115.231.176.132:8000/scan" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@prescription.jpg"
```

Or use the test client:
```bash
python test_client.py
```

## Step 10: Access the API Documentation

FastAPI provides automatic API documentation:

- Swagger UI: http://115.231.176.132:8000/docs
- ReDoc: http://115.231.176.132:8000/redoc

## Troubleshooting

### GPU Not Detected
```bash
# Check CUDA availability
python -c "import torch; print(torch.cuda.is_available())"
python -c "import torch; print(torch.cuda.get_device_name(0))"
```

### Port Issues
If port 8000 isn't accessible, check Vast.ai port mappings:
- Your instance has ports 53988-54038 mapped
- Try using a port within this range
- Update uvicorn command: `--port 54000`

### Model Loading Issues
- Ensure model files are in correct directory
- Check model format (PyTorch, SafeTensors, etc.)
- Verify model is compatible with your transformers version

### Memory Issues (OOM)
- Use FP16: `torch_dtype=torch.float16`
- Reduce batch size
- Enable gradient checkpointing
- Use model quantization (8-bit or 4-bit)

## Production Deployment

For production, consider:

1. **Use environment variables**:
```bash
export MODEL_PATH=/workspace/models/prescription_scanner_model
export API_KEY=your-secret-key
```

2. **Add authentication**:
```python
from fastapi.security import HTTPBearer
```

3. **Use process manager**:
```bash
# Install supervisor or systemd service
pip install supervisor
```

4. **Add logging**:
```python
import logging
logging.basicConfig(
    filename='/var/log/prescription_scanner.log',
    level=logging.INFO
)
```

5. **Rate limiting**:
```bash
pip install slowapi
```

## Model Fine-tuning Tips

If you haven't fine-tuned your model yet, consider:

1. **Use a vision-language model**:
   - Microsoft Florence-2
   - Google PaliGemma
   - OpenAI CLIP + GPT
   - Donut (Document Understanding Transformer)

2. **Dataset preparation**:
   - Collect prescription images
   - Annotate with medication names, dosages, etc.
   - Use data augmentation (rotations, brightness, etc.)

3. **Training**:
   - Use LoRA for efficient fine-tuning
   - Monitor validation metrics
   - Save checkpoints regularly

## API Endpoints

- `GET /` - Root endpoint
- `GET /health` - Health check
- `POST /scan` - Scan single prescription
- `POST /scan-batch` - Scan multiple prescriptions
- `POST /load-model` - Load or reload model

## Next Steps

1. Integrate with your frontend
2. Add database for storing results
3. Implement user authentication
4. Add error handling and logging
5. Set up monitoring (Prometheus, Grafana)
6. Deploy with Docker/Kubernetes for scaling
