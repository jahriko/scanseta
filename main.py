from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import torch
from PIL import Image
import io
import logging
from datetime import datetime
import os
from transformers import AutoProcessor, AutoModelForVision2Seq
from peft import PeftModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Prescription Scanner API",
    description="API for scanning and processing prescription images",
    version="1.0.0"
)

# CORS middleware for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Response Models
class MedicationInfo(BaseModel):
    name: str
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    confidence: float

class PrescriptionResponse(BaseModel):
    success: bool
    medications: List[MedicationInfo]
    raw_text: Optional[str] = None
    doctor_name: Optional[str] = None
    patient_name: Optional[str] = None
    date: Optional[str] = None
    processing_time: float

# Helper function to load Qwen VL with LoRA adapter
def load_qwen_vl_with_lora(base_model_id: str, adapter_repo: Optional[str]):
    """Load Qwen2.5-VL base model and attach LoRA adapter from Hugging Face"""
    logger.info(f"Loading base model: {base_model_id}")
    processor = AutoProcessor.from_pretrained(base_model_id, trust_remote_code=True)
    
    logger.info("Loading model with FP16 precision")
    model = AutoModelForVision2Seq.from_pretrained(
        base_model_id,
        trust_remote_code=True,
        torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
        device_map="auto",
    )
    
    if adapter_repo:
        logger.info(f"Attaching LoRA adapter: {adapter_repo}")
        model = PeftModel.from_pretrained(model, adapter_repo)
    else:
        logger.info("No adapter repo provided. Using base model only.")
    model.eval()
    
    logger.info("Model and adapter loaded successfully")
    return processor, model

# Model Configuration
class ModelConfig:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = None
        self.processor = None
        logger.info(f"Using device: {self.device}")
    
    def load_model(self, base_model: str, adapter_repo: Optional[str]):
        """Load Qwen2.5-VL base model with LoRA adapter"""
        try:
            logger.info(f"Loading base model: {base_model} with adapter: {adapter_repo}")
            self.processor, self.model = load_qwen_vl_with_lora(base_model, adapter_repo)
            logger.info("Model loaded successfully")
            
        except Exception as e:
            logger.error(f"Error loading model: {e}")
            raise

    def predict(self, image: Image.Image) -> dict:
        """Run inference on prescription image using Qwen VL chat template"""
        try:
            start_time = datetime.now()
            
            try:
                from qwen_vl_utils import process_vision_info
            except ImportError as exc:
                raise RuntimeError(
                    "Missing dependency 'qwen-vl-utils'. Install it with `pip install qwen-vl-utils`."
                ) from exc

            # Build messages with image and prompt
            messages = [{
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {
                        "type": "text",
                        "text": " ".join([
                            "You are a medical OCR engine. Extract only the drug names from this prescription.",
                            "Output format: plain comma-separated list. Exclude: all numbers, units (mg/ml/tabs).",
                            "Remove dosages, frequencies (BID/daily), and instructions. Return only the drug names."
                        ])
                    },
                ],
            }]
            
            # Apply chat template
            chat_text = self.processor.apply_chat_template(
                messages, 
                add_generation_prompt=True, 
                tokenize=False
            )
            
            # Prepare multimodal inputs with proper vision metadata
            image_inputs, video_inputs = process_vision_info(messages)

            # Process inputs
            inputs = self.processor(
                text=[chat_text],
                images=image_inputs,
                videos=video_inputs,
                padding=True,
                return_tensors="pt"
            )
            inputs = inputs.to(self.model.device)

            if "pixel_values" in inputs:
                model_dtype = next(self.model.parameters()).dtype
                inputs["pixel_values"] = inputs["pixel_values"].to(dtype=model_dtype)
            
            # Generate prediction
            with torch.no_grad():
                output = self.model.generate(**inputs, max_new_tokens=512)
            
            # Decode only the generated tokens (skip input)
            generated_ids = output[0][inputs["input_ids"].shape[-1]:]
            result_text = self.processor.decode(generated_ids, skip_special_tokens=True)
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            return {
                "raw_text": result_text,
                "processing_time": processing_time
            }
            
        except Exception as e:
            logger.error(f"Prediction error: {e}")
            raise

# Initialize model config
model_config = ModelConfig()

@app.on_event("startup")
async def startup_event():
    """Load model on startup from environment variables"""
    base_model = os.getenv("HF_BASE_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct")
    adapter_repo = os.getenv("HF_ADAPTER_REPO")
    
    if adapter_repo:
        try:
            logger.info(f"Loading model on startup: {base_model} + {adapter_repo}")
            model_config.load_model(base_model, adapter_repo)
        except Exception as e:
            logger.warning(f"Could not load model on startup: {e}")
            logger.warning("Model will need to be loaded manually via /load-model endpoint")
    else:
        logger.info("HF_ADAPTER_REPO not set. Model will need to be loaded via /load-model endpoint")

@app.get("/")
async def root():
    return {
        "message": "Prescription Scanner API",
        "status": "running",
        "model_loaded": model_config.model is not None
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "model_loaded": model_config.model is not None,
        "device": model_config.device,
        "gpu_available": torch.cuda.is_available()
    }

@app.post("/load-model")
async def load_model(base_model: str, adapter_repo: Optional[str] = None):
    """Manually load or reload the model with base model and adapter"""
    try:
        model_config.load_model(base_model, adapter_repo)
        return {
            "success": True, 
            "message": "Model loaded successfully",
            "base_model": base_model,
            "adapter_repo": adapter_repo
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/scan", response_model=PrescriptionResponse)
async def scan_prescription(file: UploadFile = File(...)):
    """
    Main endpoint to scan prescription images
    """
    if model_config.model is None:
        raise HTTPException(
            status_code=503,
            detail="Model not loaded. Please load model first via /load-model endpoint"
        )
    
    # Validate file type
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    
    try:
        # Read and process image
        image_data = await file.read()
        image = Image.open(io.BytesIO(image_data)).convert("RGB")
        
        # Run model prediction
        result = model_config.predict(image)
        
        # Parse the result (customize based on your model's output format)
        medications = parse_prescription_text(result["raw_text"])
        
        return PrescriptionResponse(
            success=True,
            medications=medications,
            raw_text=result["raw_text"],
            processing_time=result["processing_time"]
        )
        
    except Exception as e:
        logger.error(f"Error processing prescription: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/scan-batch")
async def scan_batch(files: List[UploadFile] = File(...)):
    """
    Batch processing endpoint for multiple prescriptions
    """
    if model_config.model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    results = []
    for file in files:
        try:
            image_data = await file.read()
            image = Image.open(io.BytesIO(image_data)).convert("RGB")
            result = model_config.predict(image)
            medications = parse_prescription_text(result["raw_text"])
            
            results.append({
                "filename": file.filename,
                "success": True,
                "medications": medications,
                "processing_time": result["processing_time"]
            })
        except Exception as e:
            results.append({
                "filename": file.filename,
                "success": False,
                "error": str(e)
            })
    
    return {"results": results, "total": len(files)}

def parse_prescription_text(text: str) -> List[MedicationInfo]:
    """
    Parse the model output into structured medication information
    Customize this based on your model's output format
    """
    # This is a placeholder - adjust based on your model's actual output
    medications = []
    
    # Example parsing logic (you'll need to customize this)
    lines = text.split('\n')
    for line in lines:
        if any(keyword in line.lower() for keyword in ['medication', 'drug', 'prescription']):
            medications.append(MedicationInfo(
                name=line.strip(),
                dosage=None,
                frequency=None,
                confidence=0.9
            ))
    
    return medications if medications else [
        MedicationInfo(
            name="Unable to parse medications",
            dosage=None,
            frequency=None,
            confidence=0.0
        )
    ]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
