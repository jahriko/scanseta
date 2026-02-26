from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Tuple
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
try:
    from huggingface_hub.utils._http import close_session as close_hf_session
except Exception:  # pragma: no cover - defensive fallback
    close_hf_session = None
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


ALLOWED_LOAD_POLICIES = {"fail_fast", "fallback_auto", "fallback_auto_cpu"}
DEFAULT_LOAD_POLICY = "fail_fast"


def _resolve_load_policy() -> str:
    raw_policy = os.getenv("HF_LOAD_POLICY", DEFAULT_LOAD_POLICY).strip().lower()
    if raw_policy in ALLOWED_LOAD_POLICIES:
        return raw_policy

    logger.warning(
        "Invalid HF_LOAD_POLICY=%s. Falling back to %s.",
        raw_policy,
        DEFAULT_LOAD_POLICY,
    )
    return DEFAULT_LOAD_POLICY


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


def _resolve_device_map_configuration() -> Dict[str, Any]:
    configured_device_map_raw = os.getenv("HF_DEVICE_MAP")
    if configured_device_map_raw is None or not configured_device_map_raw.strip():
        configured_device_map_raw = "cuda:0" if torch.cuda.is_available() else "cpu"
        source = "default"
    else:
        configured_device_map_raw = configured_device_map_raw.strip()
        source = "env"

    single_device_target: Optional[str] = None
    if configured_device_map_raw.startswith("cuda") or configured_device_map_raw == "cpu":
        resolved_device_map: Any = {"": configured_device_map_raw}
        single_device_target = configured_device_map_raw
        mode = "single_gpu" if configured_device_map_raw.startswith("cuda") else "cpu"
    elif configured_device_map_raw == "auto":
        resolved_device_map = "auto"
        mode = "auto"
    else:
        resolved_device_map = configured_device_map_raw
        mode = "custom"

    return {
        "raw": configured_device_map_raw,
        "resolved": resolved_device_map,
        "single_device_target": single_device_target,
        "source": source,
        "mode": mode,
    }


def _offloaded_language_modules(model: Any) -> List[str]:
    device_map = getattr(model, "hf_device_map", None)
    if not isinstance(device_map, dict):
        return []

    language_modules = {
        module_name: device
        for module_name, device in device_map.items()
        if "language_model" in module_name
        or module_name.endswith("lm_head")
        or ".lm_head" in module_name
    }
    if not language_modules:
        return []
    return [
        module_name
        for module_name, device in language_modules.items()
        if not _is_gpu_device(device)
    ]


def _model_language_on_gpu(model: Any) -> Tuple[bool, List[str]]:
    offloaded = _offloaded_language_modules(model)
    if offloaded:
        return False, offloaded

    device_map = getattr(model, "hf_device_map", None)
    if isinstance(device_map, dict):
        language_entries = [
            module_name
            for module_name in device_map
            if "language_model" in module_name
            or module_name.endswith("lm_head")
            or ".lm_head" in module_name
        ]
        if language_entries:
            return True, []

    try:
        first_parameter_device = str(next(model.parameters()).device)
    except StopIteration:
        first_parameter_device = "cpu"
    return first_parameter_device.startswith("cuda"), []


def _retry_on_closed_hf_client(load_callable, *, stage: str, max_retries: int = 1):
    attempts = 0
    while True:
        try:
            return load_callable()
        except RuntimeError as exc:
            if "client has been closed" not in str(exc).lower() or attempts >= max_retries:
                raise
            attempts += 1
            logger.warning(
                "Closed Hugging Face HTTP client while loading %s (retry %d/%d).",
                stage,
                attempts,
                max_retries,
            )
            if close_hf_session is not None:
                try:
                    close_hf_session()
                except Exception as close_exc:  # pragma: no cover - defensive fallback
                    logger.debug("Failed to reset Hugging Face HTTP client session: %s", close_exc)


def _raise_model_source_error(
    *,
    stage: str,
    base_model_id: str,
    local_files_only: bool,
    error: Exception,
) -> None:
    local_mode_hint = (
        "HF_LOCAL_FILES_ONLY=1 is enabled; only local files/cache will be used. "
        if local_files_only
        else "Model files are downloaded from Hugging Face when not already cached. "
    )
    raise RuntimeError(
        f"Failed to load {stage} for '{base_model_id}': {error}. "
        f"{local_mode_hint}"
        "Set HF_BASE_MODEL to a local model directory that contains model and processor files, "
        "or allow outbound HTTPS access to huggingface.co."
    ) from error


# Helper function to load Qwen VL with LoRA adapter
def load_qwen_vl_with_lora(base_model_id: str, adapter_repo: Optional[str]):
    if AutoModelForVision2Seq is None:
        raise RuntimeError(
            "No compatible vision-to-sequence auto model class found in transformers. "
            "Install a compatible transformers version or update model loader mappings."
        )

    # Set cache directories before any Hugging Face load call so processor/model
    # resolution uses the intended location on first attempt.
    hf_home = os.getenv("HF_HOME", os.path.abspath("./hf_home"))
    transformers_cache = os.getenv("TRANSFORMERS_CACHE", os.path.abspath("./hf_cache"))
    os.environ["HF_HOME"] = hf_home
    os.environ["TRANSFORMERS_CACHE"] = transformers_cache
    os.makedirs(hf_home, exist_ok=True)
    os.makedirs(transformers_cache, exist_ok=True)

    local_files_only = _truthy_env(os.getenv("HF_LOCAL_FILES_ONLY", "0"))
    processor_kwargs: Dict[str, Any] = {"trust_remote_code": True}
    if local_files_only:
        processor_kwargs["local_files_only"] = True

    try:
        processor = _retry_on_closed_hf_client(
            lambda: AutoProcessor.from_pretrained(base_model_id, **processor_kwargs),
            stage="processor",
        )
    except Exception as exc:
        _raise_model_source_error(
            stage="processor",
            base_model_id=base_model_id,
            local_files_only=local_files_only,
            error=exc,
        )

    load_policy = _resolve_load_policy()
    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    device_map_config = _resolve_device_map_configuration()
    configured_device_map_raw = device_map_config["raw"]
    configured_device_map = device_map_config["resolved"]
    single_device_target = device_map_config["single_device_target"]
    configured_device_map_mode = device_map_config["mode"]
    device_map_source = device_map_config["source"]

    offload_dir = os.getenv("HF_OFFLOAD_DIR", "./offload")
    os.makedirs(offload_dir, exist_ok=True)

    logger.info(
        "Model load config: policy=%s HF_DEVICE_MAP raw=%s source=%s resolved=%s",
        load_policy,
        configured_device_map_raw,
        device_map_source,
        configured_device_map,
    )
    if single_device_target and single_device_target.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError(
            f"HF_DEVICE_MAP={configured_device_map_raw} requested CUDA placement but CUDA is unavailable."
        )

    enable_4bit = _truthy_env(os.getenv("HF_ENABLE_4BIT", "1")) and torch.cuda.is_available()

    def _build_from_pretrained_kwargs(device_map: Any, target_device: Optional[str]) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "trust_remote_code": True,
            "dtype": dtype,
            "device_map": device_map,
            "low_cpu_mem_usage": target_device is None,
        }
        if local_files_only:
            kwargs["local_files_only"] = True
        if device_map == "auto":
            kwargs["offload_state_dict"] = True
            kwargs["offload_folder"] = offload_dir
            kwargs["offload_dir"] = offload_dir
        if enable_4bit:
            if BitsAndBytesConfig is None:
                logger.warning(
                    "HF_ENABLE_4BIT is enabled but BitsAndBytesConfig is unavailable. Continuing without 4-bit quantization."
                )
            else:
                kwargs["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_use_double_quant=True,
                )
                kwargs.pop("dtype", None)
                logger.info("Using 4-bit quantization for model loading (HF_ENABLE_4BIT=1).")
        return kwargs

    def _load_model_for_attempt(device_map: Any, target_device: Optional[str]) -> Any:
        from_pretrained_kwargs = _build_from_pretrained_kwargs(device_map, target_device)

        def _load_once(load_kwargs: Dict[str, Any]) -> Any:
            current_kwargs = dict(load_kwargs)
            while True:
                try:
                    return _retry_on_closed_hf_client(
                        lambda: AutoModelForVision2Seq.from_pretrained(
                            base_model_id,
                            **current_kwargs,
                        ),
                        stage="model weights",
                    )
                except TypeError as exc:
                    if "offload_dir" in str(exc) and "offload_dir" in current_kwargs:
                        current_kwargs.pop("offload_dir", None)
                        continue
                    if "offload_folder" in str(exc) and "offload_folder" in current_kwargs:
                        current_kwargs.pop("offload_folder", None)
                        continue
                    raise

        try:
            return _load_once(from_pretrained_kwargs)
        except ImportError as exc:
            if "bitsandbytes" not in str(exc).lower() or "quantization_config" not in from_pretrained_kwargs:
                raise
            logger.warning(
                "4-bit quantization unavailable (%s). Retrying without quantization.",
                exc,
            )
            from_pretrained_kwargs.pop("quantization_config", None)
            from_pretrained_kwargs["dtype"] = dtype
            return _load_once(from_pretrained_kwargs)

    def _attach_adapter(current_model: Any, target_device: Optional[str]) -> Any:
        if not adapter_repo:
            logger.warning("No adapter specified - using base model only (lower accuracy for prescriptions)")
            return current_model

        logger.info("Loading LoRA adapter: %s", adapter_repo)
        try:
            adapter_kwargs: Dict[str, Any] = {"low_cpu_mem_usage": False}
            if target_device:
                adapter_kwargs["torch_device"] = target_device
            current_model = PeftModel.from_pretrained(current_model, adapter_repo, **adapter_kwargs)
        except TypeError as exc:
            if "unhashable type: 'set'" not in str(exc):
                raise

            # Compatibility fallback for certain peft/accelerate versions
            # where nested set entries in _no_split_modules can break hashing.
            no_split_modules = getattr(current_model, "_no_split_modules", None)
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
                current_model._no_split_modules = list(dict.fromkeys(flattened_modules))

            logger.warning(
                "Retrying LoRA adapter load with peft/accelerate compatibility fallback."
            )
            current_model = PeftModel.from_pretrained(
                current_model,
                adapter_repo,
                low_cpu_mem_usage=False,
                torch_device=target_device,
            )
        logger.info("LoRA adapter loaded successfully")
        return current_model

    load_attempts: List[Tuple[Any, Optional[str], str, bool]] = [
        (configured_device_map, single_device_target, configured_device_map_mode, False)
    ]
    if (
        device_map_source == "default"
        and configured_device_map_mode == "single_gpu"
        and load_policy in {"fallback_auto", "fallback_auto_cpu"}
    ):
        load_attempts.append(("auto", None, "auto", True))
        if load_policy == "fallback_auto_cpu":
            load_attempts.append(({"": "cpu"}, "cpu", "cpu", True))

    attempt_count = len(load_attempts)
    last_error: Optional[Exception] = None
    for index, (attempt_device_map, attempt_target, attempt_mode, fallback_used) in enumerate(
        load_attempts,
        start=1,
    ):
        try:
            logger.info(
                "Model load attempt %d/%d: mode=%s device_map=%s",
                index,
                attempt_count,
                attempt_mode,
                attempt_device_map,
            )
            model = _load_model_for_attempt(attempt_device_map, attempt_target)
            if attempt_target:
                model.to(attempt_target)
            model = _attach_adapter(model, attempt_target)
            model.eval()

            language_model_on_gpu, offloaded_language_modules = _model_language_on_gpu(model)
            if offloaded_language_modules:
                logger.warning(
                    "Language model modules are offloaded from GPU: %s",
                    ", ".join(offloaded_language_modules[:5]),
                )

            require_gpu_language_model = (
                load_policy == "fail_fast"
                or _truthy_env(os.getenv("HF_REQUIRE_GPU_LANGUAGE_MODEL"))
            )
            if require_gpu_language_model and not language_model_on_gpu:
                raise RuntimeError(
                    "Language model is not fully on GPU. "
                    f"Offloaded modules: {', '.join(offloaded_language_modules[:5])}"
                )

            return processor, model, {
                "load_policy": load_policy,
                "device_map_mode": attempt_mode,
                "language_model_on_gpu": language_model_on_gpu,
                "degraded_mode": fallback_used,
                "resolved_device_map": attempt_device_map,
                "configured_device_map_raw": configured_device_map_raw,
            }
        except Exception as exc:
            last_error = exc
            logger.error(
                "Model load attempt %d/%d failed (mode=%s): %s",
                index,
                attempt_count,
                attempt_mode,
                exc,
            )
            if index < attempt_count:
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                continue
            break

    raise RuntimeError(
        f"Failed to load model using policy '{load_policy}': {last_error}"
    ) from last_error
# Model Configuration
class ModelConfig:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = None
        self.processor = None
        self.max_new_tokens = int(os.getenv("SCAN_MAX_NEW_TOKENS", "192"))
        self.load_policy = _resolve_load_policy()
        self.device_map_mode = "unloaded"
        self.language_model_on_gpu = False
        self.degraded_mode = False
        self.last_load_error: Optional[str] = None
        logger.info(f"Using device: {self.device}")
        logger.info(f"Using SCAN_MAX_NEW_TOKENS={self.max_new_tokens}")
    
    def is_ready(self) -> bool:
        return self.model is not None and not self.degraded_mode

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
            self.load_policy = _resolve_load_policy()
            processor, model, load_metadata = load_qwen_vl_with_lora(base_model, adapter_repo)
            self.processor = processor
            self.model = model
            self.device_map_mode = str(load_metadata.get("device_map_mode", "unknown"))
            self.language_model_on_gpu = bool(load_metadata.get("language_model_on_gpu", False))
            self.degraded_mode = bool(load_metadata.get("degraded_mode", False))
            self.last_load_error = None
            logger.info(
                "Model loaded successfully with policy=%s mode=%s degraded=%s",
                self.load_policy,
                self.device_map_mode,
                self.degraded_mode,
            )
            
        except Exception as e:
            self.last_load_error = str(e)
            logger.error(f"Error loading model: {e}")
            raise
    
    def get_status(self) -> dict:
        model_loaded = self.model is not None
        status = {
            "model_loaded": model_loaded,
            "device": self.device,
            "gpu_available": torch.cuda.is_available(),
            "load_policy": self.load_policy,
            "device_map_mode": self.device_map_mode,
            "language_model_on_gpu": bool(model_loaded and self.language_model_on_gpu),
            "degraded_mode": bool(model_loaded and self.degraded_mode),
            "last_load_error": self.last_load_error,
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
    logger.info("Drug post-processor initialized")
except Exception as e:
    logger.warning(f"Could not initialize post-processor: {e}")
    post_processor = None

SCAN_RESULT_CACHE_TTL_SECONDS = int(os.getenv("SCAN_RESULT_CACHE_TTL_SECONDS", "900"))
SCAN_RESULT_CACHE_MAX_ENTRIES = int(os.getenv("SCAN_RESULT_CACHE_MAX_ENTRIES", "64"))
_scan_result_cache: Dict[str, Dict[str, Any]] = {}
_scan_result_cache_lock = asyncio.Lock()
ENRICHMENT_JOB_TTL_SECONDS = int(os.getenv("ENRICHMENT_JOB_TTL_SECONDS", "1800"))
ENRICHMENT_FDA_TIMEOUT_SECONDS = float(os.getenv("ENRICHMENT_FDA_TIMEOUT_SECONDS", "60"))
ENRICHMENT_PNDF_TIMEOUT_SECONDS = float(os.getenv("ENRICHMENT_PNDF_TIMEOUT_SECONDS", "75"))
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
        logger.warning(reason)
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
        logger.warning(reason)
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
        logger.info("PNDF cache initialization complete")
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
        logger.info("Model loaded successfully on startup")
    except Exception as e:
        logger.error(f"Failed to load model on startup: {e}")
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
        logger.info("Server shutdown cleanup complete")
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
        "model_ready": model_config.is_ready(),
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
            "adapter_repo": adapter_repo,
            "load_policy": model_config.load_policy,
            "device_map_mode": model_config.device_map_mode,
            "degraded_mode": model_config.degraded_mode,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Model load failed",
                "error": str(e),
                "load_policy": model_config.load_policy,
                "last_load_error": model_config.last_load_error,
            },
        )

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


def _strip_json_code_fence(raw_text: str) -> str:
    if not raw_text:
        return ""
    return re.sub(
        r"^\s*```(?:json)?\s*|\s*```\s*$",
        "",
        raw_text.strip(),
        flags=re.IGNORECASE | re.DOTALL,
    ).strip()


def _extract_partial_structured_output(raw_text: str) -> Dict[str, Any]:
    """
    Recover structured fields from truncated JSON-like model output.
    This handles responses that start as valid JSON but are cut off mid-stream.
    """
    text = _strip_json_code_fence(raw_text)

    if not text:
        return {
            "medications": [],
            "doctor_name": None,
            "patient_name": None,
            "patient_sex": None,
            "patient_age": None,
            "date": None,
        }

    def _extract_with_pattern(pattern: str, source: str) -> Optional[str]:
        match = re.search(pattern, source, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return None
        return _clean_optional_str(match.group(1))

    patient_block_match = re.search(r'"patient"\s*:\s*\{(.*?)\}', text, flags=re.IGNORECASE | re.DOTALL)
    patient_block = patient_block_match.group(1) if patient_block_match else ""

    doctor_name = _extract_with_pattern(r'"doctor_name"\s*:\s*"([^"]*)"', text)
    patient_name = (
        _extract_with_pattern(r'"name"\s*:\s*"([^"]*)"', patient_block)
        or _extract_with_pattern(r'"patient_name"\s*:\s*"([^"]*)"', text)
    )
    patient_sex = (
        _extract_with_pattern(r'"sex"\s*:\s*"([^"]*)"', patient_block)
        or _extract_with_pattern(r'"patient_sex"\s*:\s*"([^"]*)"', text)
    )
    patient_age = (
        _extract_with_pattern(r'"age"\s*:\s*"([^"]*)"', patient_block)
        or _extract_with_pattern(r'"patient_age"\s*:\s*"([^"]*)"', text)
    )
    date = _extract_with_pattern(r'"date"\s*:\s*"([^"]*)"', text)

    medications: List[MedicationInfo] = []
    seen_names: set[str] = set()
    meds_section_match = re.search(r'"medications"\s*:\s*\[(.*)$', text, flags=re.IGNORECASE | re.DOTALL)
    meds_section = meds_section_match.group(1) if meds_section_match else ""

    if meds_section:
        for match in re.finditer(r'"name"\s*:\s*"([^"\r\n]+)"', meds_section, flags=re.IGNORECASE):
            name = _clean_optional_str(match.group(1))
            if not name:
                continue

            normalized_name = name.lower()
            if normalized_name in {"redacted"} or normalized_name in seen_names:
                continue
            seen_names.add(normalized_name)

            window = meds_section[match.end() : match.end() + 320]
            dosage = _extract_with_pattern(r'"dosage"\s*:\s*"([^"]*)"', window)
            signa = _extract_with_pattern(r'"(?:signa|sig)"\s*:\s*"([^"]*)"', window)
            frequency = _extract_with_pattern(r'"frequency"\s*:\s*"([^"]*)"', window)
            medications.append(
                _build_medication_info(
                    token=name,
                    dosage=dosage,
                    signa=signa,
                    frequency=frequency,
                    base_flags=["STRUCTURED_JSON_PARTIAL"],
                )
            )

    return {
        "medications": medications,
        "doctor_name": doctor_name,
        "patient_name": patient_name,
        "patient_sex": patient_sex,
        "patient_age": patient_age,
        "date": date,
    }


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
        partial = _extract_partial_structured_output(raw_text)
        if partial.get("medications"):
            return partial

        return {
            "medications": parse_prescription_text(_strip_json_code_fence(raw_text)),
            "doctor_name": partial.get("doctor_name"),
            "patient_name": partial.get("patient_name"),
            "patient_sex": partial.get("patient_sex"),
            "patient_age": partial.get("patient_age"),
            "date": partial.get("date"),
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


