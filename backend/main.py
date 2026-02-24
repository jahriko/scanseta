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
from datetime import datetime, timedelta
import os
import asyncio
import hashlib
from time import perf_counter
from uuid import uuid4
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
try:
    from transformers import BitsAndBytesConfig
except ImportError:
    BitsAndBytesConfig = None
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
    enrichment_job_id: Optional[str] = None
    enrichment_status: str = "not_requested"
    fda_enrichment_status: Optional[str] = None
    pndf_enrichment_status: Optional[str] = None
    enrichment_updated_at: Optional[str] = None


class EnrichmentRequest(BaseModel):
    drug_names: List[str]


class EnrichmentJobStatusResponse(BaseModel):
    success: bool
    job_id: str
    status: str
    fda_status: str
    pndf_status: str
    drug_names: List[str] = Field(default_factory=list)
    fda_verification: List[FDAVerificationItem] = Field(default_factory=list)
    pndf_enriched: List[PNDFEnrichmentItem] = Field(default_factory=list)
    errors: Dict[str, str] = Field(default_factory=dict)
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    updated_at: Optional[str] = None
    expires_at: Optional[str] = None


class EnrichmentRetryRequest(BaseModel):
    sources: Optional[List[str]] = None


def _truthy_env(value: Optional[str]) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _is_gpu_device(device: Any) -> bool:
    if isinstance(device, int):
        return device >= 0
    if isinstance(device, str):
        return device.startswith("cuda")
    return False


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
    configured_device_map_raw = os.getenv("HF_DEVICE_MAP", "auto").strip()
    single_device_target: Optional[str] = None
    if configured_device_map_raw.startswith("cuda") or configured_device_map_raw == "cpu":
        # Explicit single-device placement avoids accelerate meta-device sharding edge cases.
        configured_device_map: Any = {"": configured_device_map_raw}
        single_device_target = configured_device_map_raw
    else:
        configured_device_map = configured_device_map_raw

    offload_dir = os.getenv("HF_OFFLOAD_DIR", "./offload")
    os.makedirs(offload_dir, exist_ok=True)

    # Helps some accelerate/transformers combos pick it up during dispatch
    os.environ["HF_HOME"] = os.getenv("HF_HOME", os.path.abspath("./hf_home"))
    os.environ["TRANSFORMERS_CACHE"] = os.getenv("TRANSFORMERS_CACHE", os.path.abspath("./hf_cache"))

    from_pretrained_kwargs = {
        "trust_remote_code": True,
        "dtype": dtype,
        "device_map": configured_device_map,
        "offload_state_dict": True,
        "low_cpu_mem_usage": single_device_target is None,
        "offload_folder": offload_dir,
        "offload_dir": offload_dir,
    }
    logger.info(
        "Using HF_DEVICE_MAP raw=%s resolved=%s",
        configured_device_map_raw,
        configured_device_map,
    )
    if configured_device_map != "auto":
        from_pretrained_kwargs.pop("offload_state_dict", None)
        from_pretrained_kwargs.pop("offload_folder", None)
        from_pretrained_kwargs.pop("offload_dir", None)
    enable_4bit = _truthy_env(os.getenv("HF_ENABLE_4BIT", "1")) and torch.cuda.is_available()
    if enable_4bit:
        if BitsAndBytesConfig is None:
            logger.warning(
                "HF_ENABLE_4BIT is enabled but BitsAndBytesConfig is unavailable. Continuing without 4-bit quantization."
            )
        else:
            from_pretrained_kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
            )
            from_pretrained_kwargs.pop("dtype", None)
            logger.info("Using 4-bit quantization for model loading (HF_ENABLE_4BIT=1).")

    def _load_model_with_current_kwargs():
        try:
            return AutoModelForVision2Seq.from_pretrained(
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
            return AutoModelForVision2Seq.from_pretrained(
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
            return AutoModelForVision2Seq.from_pretrained(
                base_model_id,
                **fallback_kwargs,
            )

    try:
        model = _load_model_with_current_kwargs()
    except ImportError as exc:
        error_text = str(exc).lower()
        if "bitsandbytes" in error_text and "quantization_config" in from_pretrained_kwargs:
            logger.warning(
                "4-bit quantization unavailable (%s). Retrying without quantization.",
                exc,
            )
            from_pretrained_kwargs.pop("quantization_config", None)
            from_pretrained_kwargs["dtype"] = dtype
            model = _load_model_with_current_kwargs()
        else:
            raise

    if single_device_target:
        model.to(single_device_target)

    if adapter_repo:
        logger.info(f"Loading LoRA adapter: {adapter_repo}")
        try:
            adapter_kwargs: Dict[str, Any] = {"low_cpu_mem_usage": False}
            if single_device_target:
                adapter_kwargs["torch_device"] = single_device_target
            model = PeftModel.from_pretrained(model, adapter_repo, **adapter_kwargs)
        except TypeError as exc:
            if "unhashable type: 'set'" not in str(exc):
                raise

            # Compatibility fallback for certain peft/accelerate versions
            # where nested set entries in _no_split_modules can break hashing.
            no_split_modules = getattr(model, "_no_split_modules", None)
            flattened_modules: List[str] = []
            if isinstance(no_split_modules, (list, tuple, set)):
                for entry in no_split_modules:
                    if isinstance(entry, str):
                        flattened_modules.append(entry)
                    elif isinstance(entry, (list, tuple, set)):
                        flattened_modules.extend(
                            item for item in entry if isinstance(item, str)
                        )

            if flattened_modules:
                model._no_split_modules = list(dict.fromkeys(flattened_modules))

            logger.warning(
                "Retrying LoRA adapter load with peft/accelerate compatibility fallback."
            )
            model = PeftModel.from_pretrained(
                model,
                adapter_repo,
                low_cpu_mem_usage=False,
                torch_device=single_device_target,
            )
        logger.info("✓ LoRA adapter loaded successfully")
    else:
        logger.warning("⚠️  No adapter specified - using base model only (lower accuracy for prescriptions)")

    model.eval()
    device_map = getattr(model, "hf_device_map", None)
    if isinstance(device_map, dict):
        language_modules = {
            module_name: device
            for module_name, device in device_map.items()
            if "language_model" in module_name or module_name.endswith("lm_head") or ".lm_head" in module_name
        }
        offloaded_language_modules = [
            module_name
            for module_name, device in language_modules.items()
            if not _is_gpu_device(device)
        ]
        if offloaded_language_modules:
            logger.warning(
                "Language model modules are offloaded from GPU: %s. Generation will be slow.",
                ", ".join(offloaded_language_modules[:5]),
            )
            require_gpu_language_model = _truthy_env(os.getenv("HF_REQUIRE_GPU_LANGUAGE_MODEL"))
            if require_gpu_language_model:
                raise RuntimeError(
                    "HF_REQUIRE_GPU_LANGUAGE_MODEL=1 and language model is not fully on GPU."
                )
    return processor, model

# Model Configuration
class ModelConfig:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = None
        self.processor = None
        self.max_new_tokens = int(os.getenv("SCAN_MAX_NEW_TOKENS", "192"))
        logger.info(f"Using device: {self.device}")
        logger.info(f"Using SCAN_MAX_NEW_TOKENS={self.max_new_tokens}")
    
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
            start_ts = perf_counter()
            
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
            preprocess_done_ts = perf_counter()
            
            # Generate prediction
            with torch.no_grad():
                output = self.model.generate(**inputs, max_new_tokens=self.max_new_tokens)
            generate_done_ts = perf_counter()
            
            # Decode only the generated tokens (skip input)
            generated_ids = output[0][inputs["input_ids"].shape[-1]:]
            result_text = self.processor.decode(generated_ids, skip_special_tokens=True)
            decode_done_ts = perf_counter()
            
            processing_time = decode_done_ts - start_ts
            generated_tokens = int(generated_ids.shape[-1]) if hasattr(generated_ids, "shape") else 0
            logger.info(
                "predict_timing total=%.3fs preprocess=%.3fs generate=%.3fs decode=%.3fs generated_tokens=%d",
                processing_time,
                preprocess_done_ts - start_ts,
                generate_done_ts - preprocess_done_ts,
                decode_done_ts - generate_done_ts,
                generated_tokens,
            )
            
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
        max_candidates=int(os.getenv("MAX_CANDIDATES", "10")),
        max_length_delta=int(os.getenv("MAX_LENGTH_DELTA", "3")),
        min_similarity_for_edit=float(os.getenv("MIN_SIMILARITY_FOR_EDIT", "0.75")),
        ambiguity_margin=float(os.getenv("AMBIGUITY_MARGIN", "0.025")),
    )
    post_processor = DrugPostProcessor(post_processor_config)
    logger.info("✓ Drug post-processor initialized")
except Exception as e:
    logger.warning(f"Could not initialize post-processor: {e}")
    post_processor = None

SCAN_RESULT_CACHE_TTL_SECONDS = int(os.getenv("SCAN_RESULT_CACHE_TTL_SECONDS", "900"))
SCAN_RESULT_CACHE_MAX_ENTRIES = int(os.getenv("SCAN_RESULT_CACHE_MAX_ENTRIES", "64"))
_scan_result_cache: Dict[str, Dict[str, Any]] = {}
_scan_result_cache_lock = asyncio.Lock()
ENRICHMENT_JOB_TTL_SECONDS = int(os.getenv("ENRICHMENT_JOB_TTL_SECONDS", "1800"))
ENRICHMENT_FDA_TIMEOUT_SECONDS = float(os.getenv("ENRICHMENT_FDA_TIMEOUT_SECONDS", "2.5"))
ENRICHMENT_PNDF_TIMEOUT_SECONDS = float(os.getenv("ENRICHMENT_PNDF_TIMEOUT_SECONDS", "2.5"))
ENRICHMENT_MAX_DRUGS = int(os.getenv("ENRICHMENT_MAX_DRUGS", "3"))
ENRICHMENT_PERSIST_DEBOUNCE_SECONDS = float(os.getenv("ENRICHMENT_PERSIST_DEBOUNCE_SECONDS", "0.15"))
ENRICHMENT_STORE_PATH = Path(__file__).resolve().parent / "data" / "enrichment_jobs.json"
_enrichment_jobs: Dict[str, Dict[str, Any]] = {}
_enrichment_jobs_lock = asyncio.Lock()
_enrichment_job_tasks: Dict[str, asyncio.Task] = {}
_enrichment_persist_task: Optional[asyncio.Task] = None
_enrichment_persist_dirty = False


def _utcnow_iso() -> str:
    return datetime.now().isoformat()


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _normalize_retry_sources(raw_sources: Optional[List[str]]) -> List[str]:
    if not raw_sources:
        return ["fda", "pndf"]
    allowed = {"fda", "pndf"}
    normalized = [source.strip().lower() for source in raw_sources if isinstance(source, str)]
    return [source for source in normalized if source in allowed]


def _build_fda_timeout_results(drug_names: List[str], reason: str, error_code: str) -> List[Dict[str, Any]]:
    timestamp = _utcnow_iso()
    return [
        {
            "query": drug_name,
            "found": False,
            "matches": [],
            "best_match": None,
            "error": reason,
            "error_code": error_code,
            "scraped_at": timestamp,
        }
        for drug_name in drug_names
    ]


def _build_pndf_timeout_results(drug_names: List[str], reason: str, error_code: str) -> List[Dict[str, Any]]:
    timestamp = _utcnow_iso()
    return [
        {
            "name": drug_name,
            "found": False,
            "message": reason,
            "error": reason,
            "error_code": error_code,
            "scraped_at": timestamp,
        }
        for drug_name in drug_names
    ]


def _safe_job_payload(job: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(job)
    payload["drug_names"] = list(payload.get("drug_names") or [])
    payload["fda_verification"] = list(payload.get("fda_verification") or [])
    payload["pndf_enriched"] = list(payload.get("pndf_enriched") or [])
    payload["errors"] = dict(payload.get("errors") or {})
    return payload


def _list_coerce(items: Any) -> List[Dict[str, Any]]:
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _create_enrichment_job(drug_names: List[str]) -> Dict[str, Any]:
    now = datetime.now()
    expires_at = now + timedelta(seconds=max(ENRICHMENT_JOB_TTL_SECONDS, 60))
    return {
        "job_id": uuid4().hex,
        "status": "queued",
        "fda_status": "pending",
        "pndf_status": "pending",
        "drug_names": list(drug_names),
        "fda_verification": [],
        "pndf_enriched": [],
        "errors": {},
        "created_at": now.isoformat(),
        "started_at": None,
        "finished_at": None,
        "updated_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "expires_at_ts": expires_at.timestamp(),
        "retry_count": 0,
    }


async def _write_enrichment_jobs_payload(payload: Dict[str, Any]) -> None:
    ENRICHMENT_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    temp_path = ENRICHMENT_STORE_PATH.with_suffix(".tmp")

    def _write() -> None:
        temp_path.write_text(serialized, encoding="utf-8")
        temp_path.replace(ENRICHMENT_STORE_PATH)

    await asyncio.to_thread(_write)


async def _persist_enrichment_jobs_locked() -> None:
    payload = {"jobs": [_safe_job_payload(job) for job in _enrichment_jobs.values()]}
    await _write_enrichment_jobs_payload(payload)


def _queue_enrichment_jobs_persist_locked() -> None:
    global _enrichment_persist_dirty, _enrichment_persist_task
    _enrichment_persist_dirty = True
    if _enrichment_persist_task is None or _enrichment_persist_task.done():
        _enrichment_persist_task = asyncio.create_task(_persist_enrichment_jobs_worker())


async def _persist_enrichment_jobs_worker() -> None:
    global _enrichment_persist_task, _enrichment_persist_dirty

    try:
        while True:
            if ENRICHMENT_PERSIST_DEBOUNCE_SECONDS > 0:
                await asyncio.sleep(ENRICHMENT_PERSIST_DEBOUNCE_SECONDS)

            async with _enrichment_jobs_lock:
                if not _enrichment_persist_dirty:
                    return
                _enrichment_persist_dirty = False
                payload = {"jobs": [_safe_job_payload(job) for job in _enrichment_jobs.values()]}

            try:
                await _write_enrichment_jobs_payload(payload)
            except Exception as exc:
                logger.warning(f"Could not persist enrichment jobs: {exc}")
                async with _enrichment_jobs_lock:
                    _enrichment_persist_dirty = True
                await asyncio.sleep(0.2)
    finally:
        async with _enrichment_jobs_lock:
            if _enrichment_persist_task is asyncio.current_task():
                _enrichment_persist_task = None
            if _enrichment_persist_dirty and (_enrichment_persist_task is None or _enrichment_persist_task.done()):
                _enrichment_persist_task = asyncio.create_task(_persist_enrichment_jobs_worker())


async def _flush_enrichment_jobs_persist() -> None:
    global _enrichment_persist_task

    while True:
        async with _enrichment_jobs_lock:
            if _enrichment_persist_dirty and (_enrichment_persist_task is None or _enrichment_persist_task.done()):
                _enrichment_persist_task = asyncio.create_task(_persist_enrichment_jobs_worker())
            active_task = _enrichment_persist_task
            dirty = _enrichment_persist_dirty

        if active_task and not active_task.done():
            await asyncio.shield(active_task)
            continue

        if not dirty:
            return


def _prune_expired_jobs_locked() -> None:
    now_ts = datetime.now().timestamp()
    expired_job_ids = []
    for job_id, job in _enrichment_jobs.items():
        expires_at_ts_raw = job.get("expires_at_ts")
        expires_at_ts: Optional[float] = None
        if isinstance(expires_at_ts_raw, (int, float)):
            expires_at_ts = float(expires_at_ts_raw)
        else:
            expires_at = _parse_iso_datetime(job.get("expires_at"))
            if expires_at:
                expires_at_ts = expires_at.timestamp()
                job["expires_at_ts"] = expires_at_ts
        if expires_at_ts is not None and expires_at_ts <= now_ts:
            expired_job_ids.append(job_id)

    for job_id in expired_job_ids:
        _enrichment_jobs.pop(job_id, None)
        task = _enrichment_job_tasks.pop(job_id, None)
        if task and not task.done():
            task.cancel()


async def _load_enrichment_jobs() -> None:
    if not ENRICHMENT_STORE_PATH.exists():
        return

    try:
        raw_text = await asyncio.to_thread(ENRICHMENT_STORE_PATH.read_text, "utf-8")
        data = json.loads(raw_text)
    except Exception as exc:
        logger.warning(f"Could not load enrichment jobs from disk: {exc}")
        return

    jobs_payload = data.get("jobs") if isinstance(data, dict) else []
    if not isinstance(jobs_payload, list):
        return

    loaded_jobs: Dict[str, Dict[str, Any]] = {}
    for item in jobs_payload:
        if not isinstance(item, dict):
            continue
        job_id = str(item.get("job_id") or "").strip()
        if not job_id:
            continue

        payload = _safe_job_payload(item)
        payload["job_id"] = job_id
        payload.setdefault("status", "failed")
        payload.setdefault("fda_status", "failed")
        payload.setdefault("pndf_status", "failed")
        payload.setdefault("created_at", _utcnow_iso())
        payload.setdefault("updated_at", _utcnow_iso())
        payload.setdefault("expires_at", (datetime.now() + timedelta(seconds=max(ENRICHMENT_JOB_TTL_SECONDS, 60))).isoformat())
        expires_at = _parse_iso_datetime(payload.get("expires_at"))
        if expires_at:
            payload["expires_at_ts"] = expires_at.timestamp()
        else:
            fallback_expires = datetime.now() + timedelta(seconds=max(ENRICHMENT_JOB_TTL_SECONDS, 60))
            payload["expires_at"] = fallback_expires.isoformat()
            payload["expires_at_ts"] = fallback_expires.timestamp()
        loaded_jobs[job_id] = payload

    _enrichment_jobs.update(loaded_jobs)
    _prune_expired_jobs_locked()
    logger.info(f"Loaded {len(_enrichment_jobs)} enrichment jobs from disk")


def _job_to_status_response(job: Dict[str, Any]) -> EnrichmentJobStatusResponse:
    return EnrichmentJobStatusResponse(
        success=True,
        job_id=str(job.get("job_id", "")),
        status=str(job.get("status", "failed")),
        fda_status=str(job.get("fda_status", "failed")),
        pndf_status=str(job.get("pndf_status", "failed")),
        drug_names=list(job.get("drug_names") or []),
        fda_verification=[_to_fda_item(item) for item in _list_coerce(job.get("fda_verification"))],
        pndf_enriched=[_to_pndf_item(item) for item in _list_coerce(job.get("pndf_enriched"))],
        errors={str(key): str(value) for key, value in dict(job.get("errors") or {}).items()},
        created_at=job.get("created_at"),
        started_at=job.get("started_at"),
        finished_at=job.get("finished_at"),
        updated_at=job.get("updated_at"),
        expires_at=job.get("expires_at"),
    )


def _enrichment_status_from_sources(fda_status: str, pndf_status: str) -> str:
    terminal_success = {"completed"}
    terminal_failure = {"failed", "timed_out"}
    if fda_status in terminal_success and pndf_status in terminal_success:
        return "completed"
    if (fda_status in terminal_success and pndf_status in terminal_failure) or (
        pndf_status in terminal_success and fda_status in terminal_failure
    ):
        return "partial"
    if fda_status == "timed_out" and pndf_status == "timed_out":
        return "timed_out"
    if fda_status in terminal_failure and pndf_status in terminal_failure:
        return "failed"
    if fda_status == "pending" and pndf_status == "pending":
        return "queued"
    return "running"


async def _execute_fda_lookup(drug_names: List[str]) -> Dict[str, Any]:
    try:
        lookup_task = asyncio.create_task(FDAVerificationScraper.verify_medications(drug_names))
        done, _ = await asyncio.wait({lookup_task}, timeout=ENRICHMENT_FDA_TIMEOUT_SECONDS)
        if lookup_task not in done:
            lookup_task.cancel()
            raise asyncio.TimeoutError
        raw_results = lookup_task.result()
        return {
            "status": "completed",
            "results": [_model_dump_compat(_to_fda_item(item)) for item in raw_results],
            "error": "",
        }
    except asyncio.TimeoutError:
        reason = f"FDA validation timed out after {ENRICHMENT_FDA_TIMEOUT_SECONDS:.1f}s"
        return {
            "status": "timed_out",
            "results": _build_fda_timeout_results(drug_names, reason, "timeout"),
            "error": reason,
        }
    except Exception as exc:
        reason = f"FDA validation failed: {exc}"
        return {
            "status": "failed",
            "results": _build_fda_timeout_results(drug_names, reason, "scrape_error"),
            "error": reason,
        }


async def _execute_pndf_lookup(drug_names: List[str]) -> Dict[str, Any]:
    try:
        lookup_task = asyncio.create_task(PNDFScraper.enrich_medications(drug_names))
        done, _ = await asyncio.wait({lookup_task}, timeout=ENRICHMENT_PNDF_TIMEOUT_SECONDS)
        if lookup_task not in done:
            lookup_task.cancel()
            raise asyncio.TimeoutError
        raw_results = lookup_task.result()
        return {
            "status": "completed",
            "results": [_model_dump_compat(_to_pndf_item(item)) for item in raw_results],
            "error": "",
        }
    except asyncio.TimeoutError:
        reason = f"PNDF validation timed out after {ENRICHMENT_PNDF_TIMEOUT_SECONDS:.1f}s"
        return {
            "status": "timed_out",
            "results": _build_pndf_timeout_results(drug_names, reason, "timeout"),
            "error": reason,
        }
    except Exception as exc:
        reason = f"PNDF validation failed: {exc}"
        return {
            "status": "failed",
            "results": _build_pndf_timeout_results(drug_names, reason, "scrape_error"),
            "error": reason,
        }


async def _run_enrichment_job(job_id: str) -> None:
    async with _enrichment_jobs_lock:
        job = _enrichment_jobs.get(job_id)
        if not job:
            return
        job["status"] = "running"
        job["started_at"] = job.get("started_at") or _utcnow_iso()
        job["updated_at"] = _utcnow_iso()
        _prune_expired_jobs_locked()
        _queue_enrichment_jobs_persist_locked()

    async with _enrichment_jobs_lock:
        job = _enrichment_jobs.get(job_id)
        if not job:
            return
        drug_names = list(job.get("drug_names") or [])
        run_fda = job.get("fda_status") != "completed"
        run_pndf = job.get("pndf_status") != "completed"
        if run_fda:
            job["fda_status"] = "running"
        if run_pndf:
            job["pndf_status"] = "running"
        job["updated_at"] = _utcnow_iso()
        _queue_enrichment_jobs_persist_locked()

    fda_task = _execute_fda_lookup(drug_names) if run_fda else None
    pndf_task = _execute_pndf_lookup(drug_names) if run_pndf else None

    fda_result = {"status": "completed", "results": [], "error": ""}
    pndf_result = {"status": "completed", "results": [], "error": ""}

    if fda_task and pndf_task:
        fda_result, pndf_result = await asyncio.gather(fda_task, pndf_task)
    elif fda_task:
        fda_result = await fda_task
    elif pndf_task:
        pndf_result = await pndf_task

    async with _enrichment_jobs_lock:
        job = _enrichment_jobs.get(job_id)
        if not job:
            return

        errors = dict(job.get("errors") or {})
        if run_fda:
            job["fda_status"] = fda_result.get("status", "failed")
            job["fda_verification"] = _list_coerce(fda_result.get("results"))
            if fda_result.get("error"):
                errors["fda"] = str(fda_result["error"])
            else:
                errors.pop("fda", None)

        if run_pndf:
            job["pndf_status"] = pndf_result.get("status", "failed")
            job["pndf_enriched"] = _list_coerce(pndf_result.get("results"))
            if pndf_result.get("error"):
                errors["pndf"] = str(pndf_result["error"])
            else:
                errors.pop("pndf", None)

        job["errors"] = errors
        job["status"] = _enrichment_status_from_sources(str(job.get("fda_status")), str(job.get("pndf_status")))
        job["updated_at"] = _utcnow_iso()
        if job["status"] in {"completed", "partial", "failed", "timed_out"}:
            job["finished_at"] = _utcnow_iso()
        _queue_enrichment_jobs_persist_locked()


def _register_enrichment_task(job_id: str, task: asyncio.Task) -> None:
    _enrichment_job_tasks[job_id] = task

    def _cleanup(done_task: asyncio.Task) -> None:
        _enrichment_job_tasks.pop(job_id, None)
        if done_task.cancelled():
            return
        exc = done_task.exception()
        if exc:
            logger.error(f"Enrichment job {job_id} crashed: {exc}")

    task.add_done_callback(_cleanup)


async def _start_enrichment_job(job_id: str) -> None:
    existing = _enrichment_job_tasks.get(job_id)
    if existing and not existing.done():
        return
    task = asyncio.create_task(_run_enrichment_job(job_id))
    _register_enrichment_task(job_id, task)


async def _create_and_start_enrichment_job(drug_names: List[str]) -> Dict[str, Any]:
    filtered_drug_names = normalize_manual_drug_names(drug_names)
    if ENRICHMENT_MAX_DRUGS > 0:
        filtered_drug_names = filtered_drug_names[:ENRICHMENT_MAX_DRUGS]

    async with _enrichment_jobs_lock:
        _prune_expired_jobs_locked()
        job = _create_enrichment_job(filtered_drug_names)
        _enrichment_jobs[job["job_id"]] = job
        _queue_enrichment_jobs_persist_locked()

    await _start_enrichment_job(job["job_id"])
    return job


async def _get_enrichment_job(job_id: str) -> Optional[Dict[str, Any]]:
    async with _enrichment_jobs_lock:
        _prune_expired_jobs_locked()
        job = _enrichment_jobs.get(job_id)
        if not job:
            return None
        return _safe_job_payload(job)


async def _retry_enrichment_job(job_id: str, sources: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    retry_sources = _normalize_retry_sources(sources)
    if not retry_sources:
        return await _get_enrichment_job(job_id)

    async with _enrichment_jobs_lock:
        _prune_expired_jobs_locked()
        job = _enrichment_jobs.get(job_id)
        if not job:
            return None

        errors = dict(job.get("errors") or {})
        if "fda" in retry_sources:
            job["fda_status"] = "pending"
            job["fda_verification"] = []
            errors.pop("fda", None)
        if "pndf" in retry_sources:
            job["pndf_status"] = "pending"
            job["pndf_enriched"] = []
            errors.pop("pndf", None)

        job["errors"] = errors
        job["status"] = "queued"
        job["finished_at"] = None
        job["updated_at"] = _utcnow_iso()
        job["retry_count"] = int(job.get("retry_count", 0)) + 1
        _queue_enrichment_jobs_persist_locked()

    await _start_enrichment_job(job_id)
    return await _get_enrichment_job(job_id)


async def _initialize_enrichment_jobs() -> None:
    async with _enrichment_jobs_lock:
        _enrichment_jobs.clear()
        await _load_enrichment_jobs()
        resumable_jobs = [
            job_id
            for job_id, job in _enrichment_jobs.items()
            if str(job.get("status")) in {"queued", "running"}
        ]
        await _persist_enrichment_jobs_locked()

    for job_id in resumable_jobs:
        await _start_enrichment_job(job_id)


def _model_dump_compat(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()  # type: ignore[attr-defined]
    return model.dict()  # type: ignore[attr-defined]


def _compute_scan_cache_key(image_bytes: bytes) -> str:
    return hashlib.sha256(image_bytes).hexdigest()


async def _get_cached_scan_response(cache_key: str) -> Optional[Dict[str, Any]]:
    if SCAN_RESULT_CACHE_TTL_SECONDS <= 0 or SCAN_RESULT_CACHE_MAX_ENTRIES <= 0:
        return None

    now_ts = datetime.now().timestamp()
    async with _scan_result_cache_lock:
        cached = _scan_result_cache.get(cache_key)
        if not cached:
            return None

        stored_at_ts = float(cached.get("stored_at_ts", 0.0))
        if now_ts - stored_at_ts > SCAN_RESULT_CACHE_TTL_SECONDS:
            _scan_result_cache.pop(cache_key, None)
            return None

        response = cached.get("response")
        if isinstance(response, dict):
            return dict(response)
        return None


async def _store_cached_scan_response(cache_key: str, response: PrescriptionResponse) -> None:
    if SCAN_RESULT_CACHE_TTL_SECONDS <= 0 or SCAN_RESULT_CACHE_MAX_ENTRIES <= 0:
        return

    now_ts = datetime.now().timestamp()
    payload = _model_dump_compat(response)

    async with _scan_result_cache_lock:
        _scan_result_cache[cache_key] = {
            "stored_at_ts": now_ts,
            "response": payload,
        }

        expiry_cutoff = now_ts - SCAN_RESULT_CACHE_TTL_SECONDS
        expired_keys = [
            key
            for key, entry in _scan_result_cache.items()
            if float(entry.get("stored_at_ts", 0.0)) < expiry_cutoff
        ]
        for key in expired_keys:
            _scan_result_cache.pop(key, None)

        if len(_scan_result_cache) > SCAN_RESULT_CACHE_MAX_ENTRIES:
            oldest_keys = sorted(
                _scan_result_cache.keys(),
                key=lambda key: float(_scan_result_cache[key].get("stored_at_ts", 0.0)),
            )[: len(_scan_result_cache) - SCAN_RESULT_CACHE_MAX_ENTRIES]
            for key in oldest_keys:
                _scan_result_cache.pop(key, None)

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
    
    await _initialize_enrichment_jobs()

    # Initialize PNDF cache in background (non-blocking)
    asyncio.create_task(initialize_pndf_cache())

@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources on server shutdown"""
    try:
        async with _scan_result_cache_lock:
            _scan_result_cache.clear()
        async with _enrichment_jobs_lock:
            running_tasks = list(_enrichment_job_tasks.values())
            for task in running_tasks:
                if not task.done():
                    task.cancel()
            _enrichment_job_tasks.clear()
            _queue_enrichment_jobs_persist_locked()
        await _flush_enrichment_jobs_persist()
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

        fda_result, pndf_result = await asyncio.gather(
            _execute_fda_lookup(normalized_drug_names),
            _execute_pndf_lookup(normalized_drug_names),
        )
        fda_verification_raw = _list_coerce(fda_result.get("results"))
        pndf_enriched_raw = _list_coerce(pndf_result.get("results"))

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


@app.post("/enrichment-jobs", response_model=EnrichmentJobStatusResponse)
async def create_enrichment_job(request: EnrichmentRequest):
    normalized_drug_names = normalize_manual_drug_names(request.drug_names)
    if not normalized_drug_names:
        raise HTTPException(status_code=400, detail="No valid medication names supplied for enrichment")

    job = await _create_and_start_enrichment_job(normalized_drug_names)
    return _job_to_status_response(job)


@app.get("/enrichment-jobs/{job_id}", response_model=EnrichmentJobStatusResponse)
async def get_enrichment_job(job_id: str):
    job = await _get_enrichment_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Enrichment job not found or expired")
    return _job_to_status_response(job)


@app.get("/enrichment-jobs/{job_id}/results", response_model=EnrichmentJobStatusResponse)
async def get_enrichment_job_results(job_id: str):
    job = await _get_enrichment_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Enrichment job not found or expired")
    return _job_to_status_response(job)


@app.post("/enrichment-jobs/{job_id}/retry", response_model=EnrichmentJobStatusResponse)
async def retry_enrichment_job(job_id: str, request: Optional[EnrichmentRetryRequest] = None):
    sources = request.sources if request else None
    job = await _retry_enrichment_job(job_id, sources=sources)
    if not job:
        raise HTTPException(status_code=404, detail="Enrichment job not found or expired")
    return _job_to_status_response(job)

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
        request_started_ts = perf_counter()
        request_started_at = datetime.now()
        image_data = await file.read()
        read_done_ts = perf_counter()
        cache_key = _compute_scan_cache_key(image_data)

        cached_response = await _get_cached_scan_response(cache_key)
        cache_lookup_done_ts = perf_counter()
        if cached_response:
            cached_job_id = cached_response.get("enrichment_job_id")
            if isinstance(cached_job_id, str) and cached_job_id.strip():
                job = await _get_enrichment_job(cached_job_id)
                if job:
                    cached_response["enrichment_status"] = job.get("status")
                    cached_response["fda_enrichment_status"] = job.get("fda_status")
                    cached_response["pndf_enrichment_status"] = job.get("pndf_status")
                    cached_response["enrichment_updated_at"] = job.get("updated_at")
                    cached_response["fda_verification"] = _list_coerce(job.get("fda_verification"))
                    cached_response["pndf_enriched"] = _list_coerce(job.get("pndf_enriched"))
                    cached_response["enriched"] = _list_coerce(job.get("pndf_enriched"))
            cache_refresh_done_ts = perf_counter()

            cached_response["processing_time"] = max(
                (datetime.now() - request_started_at).total_seconds(),
                0.001,
            )
            logger.info(
                "scan_timing cache_hit=true total=%.3fs read=%.3fs cache_lookup=%.3fs cached_refresh=%.3fs",
                cache_refresh_done_ts - request_started_ts,
                read_done_ts - request_started_ts,
                cache_lookup_done_ts - read_done_ts,
                cache_refresh_done_ts - cache_lookup_done_ts,
            )
            logger.info("Returning cached scan result")
            return PrescriptionResponse(**cached_response)

        image = Image.open(io.BytesIO(image_data)).convert("RGB")
        image_decode_done_ts = perf_counter()

        result = await asyncio.to_thread(model_config.predict, image)
        predict_done_ts = perf_counter()
        parsed_output = parse_model_output(result["raw_text"])
        medications = parsed_output["medications"]
        parse_done_ts = perf_counter()

        drug_names = extract_enrichment_candidates(medications)
        candidate_extract_done_ts = perf_counter()
        enrichment_job: Optional[Dict[str, Any]] = None
        fda_verification_data: Optional[List[FDAVerificationItem]] = None
        pndf_enriched_data: Optional[List[PNDFEnrichmentItem]] = None
        enrichment_status = "not_requested"
        fda_enrichment_status: Optional[str] = None
        pndf_enrichment_status: Optional[str] = None
        enrichment_updated_at: Optional[str] = None
        enrichment_job_id: Optional[str] = None
        enrichment_queue_done_ts = candidate_extract_done_ts

        if drug_names:
            try:
                enrichment_job = await _create_and_start_enrichment_job(drug_names)
                enrichment_job_id = enrichment_job.get("job_id")
                enrichment_status = str(enrichment_job.get("status", "queued"))
                fda_enrichment_status = str(enrichment_job.get("fda_status", "pending"))
                pndf_enrichment_status = str(enrichment_job.get("pndf_status", "pending"))
                enrichment_updated_at = enrichment_job.get("updated_at")
                fda_verification_data = [_to_fda_item(item) for item in _list_coerce(enrichment_job.get("fda_verification"))]
                pndf_enriched_data = [_to_pndf_item(item) for item in _list_coerce(enrichment_job.get("pndf_enriched"))]
                logger.info(f"Queued enrichment job {enrichment_job_id} for {len(drug_names)} medications")
            except Exception as e:
                logger.warning(f"Could not queue enrichment job: {e}")
                enrichment_status = "failed"
                fda_enrichment_status = "failed"
                pndf_enrichment_status = "failed"
                enrichment_updated_at = _utcnow_iso()
            finally:
                enrichment_queue_done_ts = perf_counter()

        response = PrescriptionResponse(
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
            enrichment_job_id=enrichment_job_id,
            enrichment_status=enrichment_status,
            fda_enrichment_status=fda_enrichment_status,
            pndf_enrichment_status=pndf_enrichment_status,
            enrichment_updated_at=enrichment_updated_at,
        )
        response_built_done_ts = perf_counter()

        await _store_cached_scan_response(cache_key, response)
        cache_store_done_ts = perf_counter()
        logger.info(
            (
                "scan_timing cache_hit=false total=%.3fs read=%.3fs image_decode=%.3fs "
                "predict=%.3fs parse=%.3fs candidate_extract=%.3fs "
                "queue_enrichment=%.3fs response_build=%.3fs cache_store=%.3fs "
                "medications=%d candidates=%d model_processing_time=%.3fs"
            ),
            cache_store_done_ts - request_started_ts,
            read_done_ts - request_started_ts,
            image_decode_done_ts - cache_lookup_done_ts,
            predict_done_ts - image_decode_done_ts,
            parse_done_ts - predict_done_ts,
            candidate_extract_done_ts - parse_done_ts,
            enrichment_queue_done_ts - candidate_extract_done_ts,
            response_built_done_ts - enrichment_queue_done_ts,
            cache_store_done_ts - response_built_done_ts,
            len(medications),
            len(drug_names),
            float(result.get("processing_time", 0.0)),
        )
        return response

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
            result = await asyncio.to_thread(model_config.predict, image)
            parsed_output = parse_model_output(result["raw_text"])
            medications = parsed_output["medications"]

            drug_names = extract_enrichment_candidates(medications)
            fda_verification_data = None
            pndf_enriched_data = None

            if drug_names:
                try:
                    fda_result = await _execute_fda_lookup(drug_names)
                    fda_verification_data = [_to_fda_item(item) for item in _list_coerce(fda_result.get("results"))]
                    logger.info(f"Verified {len(fda_verification_data)} medications with FDA for {file.filename}")
                except Exception as e:
                    logger.warning(f"Could not verify medications with FDA for {file.filename}: {e}")

                try:
                    pndf_result = await _execute_pndf_lookup(drug_names)
                    pndf_enriched_data = [_to_pndf_item(item) for item in _list_coerce(pndf_result.get("results"))]
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

