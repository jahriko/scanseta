from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import torch
from PIL import Image
import io
import logging
import json
import re
from datetime import datetime
import os
import asyncio
from pathlib import Path
try:
    from transformers import AutoProcessor, AutoModelForVision2Seq
except ImportError:
    from transformers import AutoProcessor
    try:
        # Transformers 5.x compatibility fallback
        from transformers import AutoModelForImageTextToText as AutoModelForVision2Seq
    except ImportError:
        AutoModelForVision2Seq = None
from peft import PeftModel
from src.scrapers.pndf_scraper import PNDFScraper
from src.scrapers.fda_verification_scraper import FDAVerificationScraper
from src.post_processing import DrugPostProcessor, PostProcessingConfig
from src.post_processing.token_processing import (
    clean_extracted_tokens,
    extract_enrichment_candidates,
    normalize_manual_drug_names,
)

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
    signa: Optional[str] = None
    frequency: Optional[str] = None
    confidence: float
    original_name: Optional[str] = None
    flags: List[str] = Field(default_factory=list)
    match_method: Optional[str] = None
    edit_distance: Optional[int] = None
    similarity: Optional[float] = None
    plausibility: Optional[float] = None


class FDAMatch(BaseModel):
    registration_number: Optional[str] = None
    generic_name: Optional[str] = None
    brand_name: Optional[str] = None
    dosage_strength: Optional[str] = None
    classification: Optional[str] = None
    details: Dict[str, str] = Field(default_factory=dict)


class FDAVerificationItem(BaseModel):
    query: str
    found: bool
    matches: List[FDAMatch] = Field(default_factory=list)
    best_match: Optional[FDAMatch] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    scraped_at: Optional[str] = None


class PNDFEnrichmentItem(BaseModel):
    name: str
    found: bool = True
    atc_code: Optional[str] = None
    classification: Optional[Dict[str, Optional[str]]] = None
    dosage_forms: List[Dict[str, Any]] = Field(default_factory=list)
    indications: Optional[str] = None
    contraindications: Optional[str] = None
    precautions: Optional[str] = None
    adverse_reactions: Optional[str] = None
    drug_interactions: Optional[str] = None
    mechanism_of_action: Optional[str] = None
    dosage_instructions: Optional[str] = None
    administration: Optional[str] = None
    pregnancy_category: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    scraped_at: Optional[str] = None


class EnrichmentResponse(BaseModel):
    success: bool
    fda_verification: List[FDAVerificationItem] = Field(default_factory=list)
    pndf_enriched: List[PNDFEnrichmentItem] = Field(default_factory=list)
    enriched_medications: List[PNDFEnrichmentItem] = Field(default_factory=list)
    count: int


class PrescriptionResponse(BaseModel):
    success: bool
    medications: List[MedicationInfo]
    raw_text: Optional[str] = None
    doctor_name: Optional[str] = None
    patient_name: Optional[str] = None
    patient_sex: Optional[str] = None
    patient_age: Optional[str] = None
    date: Optional[str] = None
    processing_time: float
    enriched: Optional[List[PNDFEnrichmentItem]] = None  # Backward compatibility: alias for pndf_enriched
    fda_verification: Optional[List[FDAVerificationItem]] = None
    pndf_enriched: Optional[List[PNDFEnrichmentItem]] = None
    can_enrich: bool = False


class EnrichmentRequest(BaseModel):
    drug_names: List[str]


def _to_pndf_item(item: Dict[str, Any]) -> PNDFEnrichmentItem:
    payload = dict(item)
    payload.setdefault("found", True)
    return PNDFEnrichmentItem(**payload)


def _to_fda_item(item: Dict[str, Any]) -> FDAVerificationItem:
    return FDAVerificationItem(**item)


# Helper function to load Qwen VL with LoRA adapter
def load_qwen_vl_with_lora(base_model_id: str, adapter_repo: Optional[str]):
    if AutoModelForVision2Seq is None:
        raise RuntimeError(
            "No compatible vision-to-sequence auto model class found in transformers. "
            "Install a compatible transformers version or update model loader mappings."
        )

    processor = AutoProcessor.from_pretrained(base_model_id, trust_remote_code=True)

    dtype = torch.float16 if torch.cuda.is_available() else torch.float32

    offload_dir = os.getenv("HF_OFFLOAD_DIR", "./offload")
    os.makedirs(offload_dir, exist_ok=True)

    # Helps some accelerate/transformers combos pick it up during dispatch
    os.environ["HF_HOME"] = os.getenv("HF_HOME", os.path.abspath("./hf_home"))
    os.environ["TRANSFORMERS_CACHE"] = os.getenv("TRANSFORMERS_CACHE", os.path.abspath("./hf_cache"))

    from_pretrained_kwargs = {
        "trust_remote_code": True,
        "dtype": dtype,
        "device_map": "auto",
        "offload_state_dict": True,
        "low_cpu_mem_usage": True,
        "offload_folder": offload_dir,
        "offload_dir": offload_dir,
    }

    try:
        model = AutoModelForVision2Seq.from_pretrained(
            base_model_id,
            **from_pretrained_kwargs,
        )
    except TypeError as exc:
        if "offload_dir" in str(exc):
            from_pretrained_kwargs.pop("offload_dir", None)
        elif "offload_folder" in str(exc):
            from_pretrained_kwargs.pop("offload_folder", None)
        else:
            raise
        model = AutoModelForVision2Seq.from_pretrained(
            base_model_id,
            **from_pretrained_kwargs,
        )
    except RuntimeError as exc:
        if "offload_dir" not in str(exc):
            raise
        logger.warning(
            "Auto device_map requires offload_dir. Falling back to CPU load."
        )
        fallback_kwargs = {
            "trust_remote_code": True,
            "dtype": torch.float32,
            "device_map": "cpu",
            "low_cpu_mem_usage": True,
        }
        model = AutoModelForVision2Seq.from_pretrained(
            base_model_id,
            **fallback_kwargs,
        )

    if adapter_repo:
        logger.info(f"Loading LoRA adapter: {adapter_repo}")
        model = PeftModel.from_pretrained(model, adapter_repo)
        logger.info("✓ LoRA adapter loaded successfully")
    else:
        logger.warning("⚠️  No adapter specified - using base model only (lower accuracy for prescriptions)")

    model.eval()
    return processor, model

# Model Configuration
class ModelConfig:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = None
        self.processor = None
        logger.info(f"Using device: {self.device}")
    
    def load_model(self, base_model: str, adapter_repo: Optional[str] = None):
        """Load Qwen2.5-VL base model with LoRA adapter
        
        For best results, always use the prescription-specific adapter.
        If adapter_repo is None, defaults to scanseta/qwen_prescription_model.
        """
        # Default to prescription adapter for best results
        if adapter_repo is None:
            adapter_repo = "scanseta/qwen_prescription_model"
            logger.info("No adapter specified, using default prescription adapter for best results")
        
        try:
            logger.info(f"Loading base model: {base_model} with adapter: {adapter_repo}")
            self.processor, self.model = load_qwen_vl_with_lora(base_model, adapter_repo)
            logger.info("✓ Model loaded successfully with prescription adapter")
            
        except Exception as e:
            logger.error(f"Error loading model: {e}")
            raise
    
    def get_status(self) -> dict:
        model_loaded = self.model is not None
        status = {
            "model_loaded": model_loaded,
            "device": self.device,
            "gpu_available": torch.cuda.is_available(),
        }
        if torch.cuda.is_available():
            status["gpu_name"] = torch.cuda.get_device_name(0)
            status["gpu_memory_allocated_mb"] = round(torch.cuda.memory_allocated(0) / 1024**2, 2)
            status["gpu_memory_reserved_mb"] = round(torch.cuda.memory_reserved(0) / 1024**2, 2)
        if model_loaded:
            status["model_dtype"] = str(next(self.model.parameters()).dtype)
            status["model_device"] = str(next(self.model.parameters()).device)
            status["hf_device_map"] = getattr(self.model, "hf_device_map", None)
        return status

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
                            "You are a medical prescription OCR extraction engine.",
                            "Return ONLY valid JSON with this exact top-level schema:",
                            '{"patient":{"name":null,"sex":null,"age":null},"doctor_name":null,"date":null,"medications":[{"name":"","dosage":null,"signa":null,"frequency":null}]}.',
                            "Use null for unknown values. Include all medications you can read.",
                            "Do not add markdown, prose, or code fences."
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

# Initialize post-processor
try:
    default_lexicon_path = Path(__file__).resolve().parent / "data" / "drug_lexicon.txt"
    post_processor_config = PostProcessingConfig(
        lexicon_path=os.getenv("LEXICON_PATH", str(default_lexicon_path)),
        max_edit_distance=int(os.getenv("MAX_EDIT_DISTANCE", "2")),
        min_similarity=float(os.getenv("MIN_SIMILARITY", "0.86")),
        ngram_n=int(os.getenv("NGRAM_N", "3")),
        plausibility_threshold=float(os.getenv("PLAUSIBILITY_THRESHOLD", "-1.0")),
        max_candidates=int(os.getenv("MAX_CANDIDATES", "10"))
    )
    post_processor = DrugPostProcessor(post_processor_config)
    logger.info("✓ Drug post-processor initialized")
except Exception as e:
    logger.warning(f"Could not initialize post-processor: {e}")
    post_processor = None

async def initialize_pndf_cache():
    """Background task to initialize/refresh PNDF cache on startup"""
    try:
        logger.info("Initializing PNDF cache...")
        await PNDFScraper.refresh_cache()
        logger.info("✓ PNDF cache initialization complete")
    except Exception as e:
        logger.warning(f"Could not initialize PNDF cache: {e}")

@app.on_event("startup")
async def startup_event():
    """Load model on startup from environment variables and refresh PNDF cache"""
    base_model = os.getenv("HF_BASE_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct")
    adapter_repo = os.getenv("HF_ADAPTER_REPO", "scanseta/qwen_prescription_model")
    
    # Always load model on startup (fail fast if it fails)
    try:
        logger.info(f"Loading model on startup: {base_model} + {adapter_repo}")
        model_config.load_model(base_model, adapter_repo)
        logger.info("✓ Model loaded successfully on startup")
    except Exception as e:
        logger.error(f"❌ Failed to load model on startup: {e}")
        logger.error("Server will not start without a loaded model")
        raise RuntimeError(f"Failed to load model: {e}") from e
    
    # Initialize PNDF cache in background (non-blocking)
    asyncio.create_task(initialize_pndf_cache())

@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources on server shutdown"""
    try:
        await PNDFScraper.cleanup()
        await FDAVerificationScraper.cleanup()
        logger.info("✓ Server shutdown cleanup complete")
    except Exception as e:
        logger.warning(f"Error during shutdown cleanup: {e}")

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

@app.get("/model-status")
async def model_status():
    return model_config.get_status()

@app.get("/load-model")
async def load_model(
    base_model: Optional[str] = None, 
    adapter_repo: Optional[str] = None
):
    """
    Manually load or reload the model with base model and adapter.
    If base_model is not provided, uses default: Qwen/Qwen2.5-VL-7B-Instruct
    If adapter_repo is not provided, uses default: scanseta/qwen_prescription_model
    """
    # Use defaults if not provided
    if base_model is None:
        base_model = os.getenv("HF_BASE_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct")
    if adapter_repo is None:
        adapter_repo = os.getenv("HF_ADAPTER_REPO", "scanseta/qwen_prescription_model")
    
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

@app.post("/enrich-medications", response_model=EnrichmentResponse)
async def enrich_medications(request: EnrichmentRequest):
    """
    Enrich extracted medication names with FDA verification and PNDF data
    Returns FDA verification results (primary) and PNDF enrichment (secondary)
    """
    try:
        normalized_drug_names = normalize_manual_drug_names(request.drug_names)
        logger.info(
            f"Enriching {len(normalized_drug_names)} normalized medications "
            f"(received {len(request.drug_names)}) with FDA and PNDF data"
        )

        fda_verification_raw = await FDAVerificationScraper.verify_medications(normalized_drug_names)
        pndf_enriched_raw = await PNDFScraper.enrich_medications(normalized_drug_names)

        fda_verification = [_to_fda_item(item) for item in fda_verification_raw]
        pndf_enriched = [_to_pndf_item(item) for item in pndf_enriched_raw]

        return EnrichmentResponse(
            success=True,
            fda_verification=fda_verification,
            pndf_enriched=pndf_enriched,
            enriched_medications=pndf_enriched,
            count=len(normalized_drug_names),
        )
    except Exception as e:
        logger.error(f"Error enriching medications: {e}")
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

    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    try:
        image_data = await file.read()
        image = Image.open(io.BytesIO(image_data)).convert("RGB")

        result = model_config.predict(image)
        parsed_output = parse_model_output(result["raw_text"])
        medications = parsed_output["medications"]

        drug_names = extract_enrichment_candidates(medications)
        fda_verification_data: Optional[List[FDAVerificationItem]] = None
        pndf_enriched_data: Optional[List[PNDFEnrichmentItem]] = None

        if drug_names:
            try:
                fda_verification_raw = await FDAVerificationScraper.verify_medications(drug_names)
                fda_verification_data = [_to_fda_item(item) for item in fda_verification_raw]
                logger.info(f"Verified {len(fda_verification_data)} medications with FDA")
            except Exception as e:
                logger.warning(f"Could not verify medications with FDA: {e}")

            try:
                pndf_enriched_raw = await PNDFScraper.enrich_medications(drug_names)
                pndf_enriched_data = [_to_pndf_item(item) for item in pndf_enriched_raw]
                logger.info(f"Enriched {len(pndf_enriched_data)} medications with PNDF")
            except Exception as e:
                logger.warning(f"Could not enrich medications with PNDF: {e}")

        return PrescriptionResponse(
            success=True,
            medications=medications,
            raw_text=result["raw_text"],
            doctor_name=parsed_output["doctor_name"],
            patient_name=parsed_output["patient_name"],
            patient_sex=parsed_output["patient_sex"],
            patient_age=parsed_output["patient_age"],
            date=parsed_output["date"],
            processing_time=result["processing_time"],
            fda_verification=fda_verification_data,
            pndf_enriched=pndf_enriched_data,
            enriched=pndf_enriched_data,
            can_enrich=bool(drug_names),
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
            parsed_output = parse_model_output(result["raw_text"])
            medications = parsed_output["medications"]

            drug_names = extract_enrichment_candidates(medications)
            fda_verification_data = None
            pndf_enriched_data = None

            if drug_names:
                try:
                    fda_verification_raw = await FDAVerificationScraper.verify_medications(drug_names)
                    fda_verification_data = [_to_fda_item(item) for item in fda_verification_raw]
                    logger.info(f"Verified {len(fda_verification_data)} medications with FDA for {file.filename}")
                except Exception as e:
                    logger.warning(f"Could not verify medications with FDA for {file.filename}: {e}")

                try:
                    pndf_enriched_raw = await PNDFScraper.enrich_medications(drug_names)
                    pndf_enriched_data = [_to_pndf_item(item) for item in pndf_enriched_raw]
                    logger.info(f"Enriched {len(pndf_enriched_data)} medications with PNDF for {file.filename}")
                except Exception as e:
                    logger.warning(f"Could not enrich medications with PNDF for {file.filename}: {e}")

            results.append({
                "filename": file.filename,
                "success": True,
                "medications": medications,
                "raw_text": result["raw_text"],
                "doctor_name": parsed_output["doctor_name"],
                "patient_name": parsed_output["patient_name"],
                "patient_sex": parsed_output["patient_sex"],
                "patient_age": parsed_output["patient_age"],
                "date": parsed_output["date"],
                "processing_time": result["processing_time"],
                "fda_verification": fda_verification_data,
                "pndf_enriched": pndf_enriched_data,
                "enriched": pndf_enriched_data,
                "can_enrich": bool(drug_names),
            })
        except Exception as e:
            results.append({
                "filename": file.filename,
                "success": False,
                "error": str(e),
            })

    return {"results": results, "total": len(files)}


def _clean_optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        value = str(value)
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned if cleaned else None


def _extract_json_object(raw_text: str) -> Optional[Dict[str, Any]]:
    text = raw_text.strip()
    if not text:
        return None

    # Strip code fences if present.
    fenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
    candidates = [fenced, text]

    # Also try first JSON-looking object in the output.
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        candidates.append(match.group(0))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    return None


def _build_medication_info(
    token: str,
    dosage: Optional[str] = None,
    signa: Optional[str] = None,
    frequency: Optional[str] = None,
    base_flags: Optional[List[str]] = None,
) -> MedicationInfo:
    flags = list(base_flags or [])
    if post_processor:
        try:
            results = post_processor.process_tokens([token])
            if results:
                result = results[0]
                final_name = result.canonical_name if result.canonical_name else result.original_name
                merged_flags = list(dict.fromkeys(flags + list(result.flags)))
                return MedicationInfo(
                    name=final_name,
                    dosage=dosage,
                    signa=signa,
                    frequency=frequency,
                    confidence=0.9,
                    original_name=result.original_name,
                    flags=merged_flags,
                    match_method=result.match_method,
                    edit_distance=result.edit_distance,
                    similarity=result.similarity,
                    plausibility=result.plausibility,
                )
        except Exception as e:
            logger.error(f"Post-processing error: {e}")
            flags = list(dict.fromkeys(flags + ["POST_PROCESS_ERROR"]))
    elif "NO_POST_PROCESSOR" not in flags:
        flags.append("NO_POST_PROCESSOR")

    return MedicationInfo(
        name=token,
        dosage=dosage,
        signa=signa,
        frequency=frequency,
        confidence=0.9,
        flags=flags,
    )


def parse_prescription_text(text: str) -> List[MedicationInfo]:
    """
    Parse model output into structured medication information.
    Uses post-processing for fuzzy matching and canonicalization.
    """
    unique_tokens = clean_extracted_tokens(text)

    if not unique_tokens:
        return [
            MedicationInfo(
                name="Unable to parse medications",
                dosage=None,
                frequency=None,
                confidence=0.0,
                flags=["PARSE_ERROR"],
            )
        ]

    medications: List[MedicationInfo] = []
    for token in unique_tokens:
        medications.append(
            _build_medication_info(
                token=token,
                dosage=None,
                signa=None,
                frequency=None,
            )
        )

    return medications


def parse_model_output(raw_text: str) -> Dict[str, Any]:
    """
    Parse structured model output first, then fall back to legacy token parsing.
    Returns medications and extracted patient/prescriber metadata.
    """
    payload = _extract_json_object(raw_text)
    if not payload:
        return {
            "medications": parse_prescription_text(raw_text),
            "doctor_name": None,
            "patient_name": None,
            "patient_sex": None,
            "patient_age": None,
            "date": None,
        }

    patient = payload.get("patient") if isinstance(payload.get("patient"), dict) else {}
    meds_payload = payload.get("medications")
    medications: List[MedicationInfo] = []

    if isinstance(meds_payload, list):
        for item in meds_payload:
            if not isinstance(item, dict):
                continue
            name = _clean_optional_str(item.get("name") or item.get("drug") or item.get("medication"))
            if not name:
                continue
            medications.append(
                _build_medication_info(
                    token=name,
                    dosage=_clean_optional_str(item.get("dosage")),
                    signa=_clean_optional_str(item.get("signa") or item.get("sig")),
                    frequency=_clean_optional_str(item.get("frequency")),
                    base_flags=["STRUCTURED_JSON"],
                )
            )

    if not medications:
        medications = parse_prescription_text(raw_text)

    return {
        "medications": medications,
        "doctor_name": _clean_optional_str(payload.get("doctor_name")),
        "patient_name": _clean_optional_str(patient.get("name")) or _clean_optional_str(payload.get("patient_name")),
        "patient_sex": _clean_optional_str(patient.get("sex")) or _clean_optional_str(payload.get("patient_sex")),
        "patient_age": _clean_optional_str(patient.get("age")) or _clean_optional_str(payload.get("patient_age")),
        "date": _clean_optional_str(payload.get("date")),
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

