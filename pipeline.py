"""
Optimized Medical Prescription OCR Pipeline
Lightweight preprocessing for printed prescriptions
Philippine National Drug Formulary (PNDF) focused
WITH ACCURACY, WER METRICS, DETAILED TIMING, AND CPU FIX
TUNED FOR HIGH-CONTRAST OUTPUT
"""

import cv2
import torch
import numpy as np
from PIL import Image
from transformers import Qwen2VLForConditionalGeneration, AutoProcessor
from peft import PeftModel
from qwen_vl_utils import process_vision_info
import os
import json
import time
from typing import Dict, List, Optional
import re

try:
    import jiwer
    JIWER_AVAILABLE = True
except ImportError:
    print("⚠️  jiwer not installed. Install with: pip install jiwer")
    JIWER_AVAILABLE = False

BASE_MODEL = "Qwen/Qwen2-VL-7B-Instruct"
TUNING_DIR = os.path.dirname(os.path.abspath(__file__))
ADAPTER_PATH = os.path.join(TUNING_DIR, "qwen25vl_rx")
OUTPUT_DIR = os.path.join(TUNING_DIR, "output")


class OCRMetrics:
    """Calculate accuracy and WER metrics for OCR output"""
    
    @staticmethod
    def calculate_wer(ground_truth: str, prediction: str) -> Dict:
        """Calculate Word Error Rate using jiwer library"""
        if not JIWER_AVAILABLE:
            return {'error': 'jiwer not installed'}
        
        gt_normalized = ground_truth.strip().lower()
        pred_normalized = prediction.strip().lower()
        
        try:
            wer_score = jiwer.wer(gt_normalized, pred_normalized)
            mer_score = jiwer.mer(gt_normalized, pred_normalized)
            wil_score = jiwer.wil(gt_normalized, pred_normalized)
            wip_score = jiwer.wip(gt_normalized, pred_normalized)
            
            from jiwer import process_words
            output = process_words(gt_normalized, pred_normalized)
            
            return {
                'wer': wer_score,
                'wer_percentage': wer_score * 100,
                'mer': mer_score,
                'wil': wil_score,
                'wip': wip_score,
                'substitutions': output.substitutions,
                'deletions': output.deletions,
                'insertions': output.insertions,
                'hits': output.hits
            }
        except Exception:
            return {
                'wer': jiwer.wer(gt_normalized, pred_normalized),
                'wer_percentage': jiwer.wer(gt_normalized, pred_normalized) * 100,
                'mer': jiwer.mer(gt_normalized, pred_normalized),
                'wil': jiwer.wil(gt_normalized, pred_normalized),
                'wip': jiwer.wip(gt_normalized, pred_normalized),
                'substitutions': 0,
                'deletions': 0,
                'insertions': 0,
                'hits': 0,
                'note': 'Detailed stats unavailable'
            }
    
    @staticmethod
    def calculate_accuracy(ground_truth: List[str], predictions: List[str]) -> Dict:
        """Calculate accuracy for drug name lists"""
        gt_set = set([drug.strip().lower() for drug in ground_truth if drug.strip()])
        pred_set = set([drug.strip().lower() for drug in predictions if drug.strip()])
        
        true_positives = len(gt_set & pred_set)
        false_positives = len(pred_set - gt_set)
        false_negatives = len(gt_set - pred_set)
        
        precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0
        recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0
        f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
        exact_match = 1.0 if gt_set == pred_set else 0.0
        
        return {
            'exact_match': exact_match,
            'exact_match_percentage': exact_match * 100,
            'precision': precision,
            'precision_percentage': precision * 100,
            'recall': recall,
            'recall_percentage': recall * 100,
            'f1_score': f1_score,
            'f1_percentage': f1_score * 100,
            'true_positives': true_positives,
            'false_positives': false_positives,
            'false_negatives': false_negatives,
            'ground_truth_drugs': sorted(list(gt_set)),
            'predicted_drugs': sorted(list(pred_set)),
            'correctly_identified': sorted(list(gt_set & pred_set)),
            'missed_drugs': sorted(list(gt_set - pred_set)),
            'false_detections': sorted(list(pred_set - gt_set))
        }



class LightweightPreprocessor:
    
    
    def __init__(self):
        self.steps = []
    
    def preprocess_image(self, 
                        image_path: str,
                        output_size: tuple = (1024, 1024),
                        save_steps: bool = False,
                        output_dir: Optional[str] = None) -> tuple:
    
        preprocessing_start = time.time()
        
        print(f"\n{'='*60}")
        print(f"📄 Processing: {os.path.basename(image_path)}")
        print(f"{'='*60}")
        
        self.steps = []
        
      
        img = cv2.imread(image_path)
        if img is None:
            raise FileNotFoundError(f"Cannot read: {image_path}")
        
        print(f"✓ Original: {img.shape[1]}x{img.shape[0]}px")
        self.steps.append(('01_original', img.copy()))
        
        
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        self.steps.append(('02_grayscale', gray.copy()))
      
        denoised = cv2.fastNlMeansDenoising(gray, None, h=7, templateWindowSize=7, searchWindowSize=15)
        self.steps.append(('03_denoised', denoised.copy()))
      
        clahe = cv2.createCLAHE(clipLimit=5.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(denoised)
        self.steps.append(('04_contrast', enhanced.copy()))
      
        kernel_sharpen = np.array([
            [-1, -1, -1],
            [-1,  9, -1],
            [-1, -1, -1]
        ])
        sharpened = cv2.filter2D(enhanced, -1, kernel_sharpen)
        print(f"✓ Strong sharpening applied")
        self.steps.append(('05_sharpened', sharpened.copy()))
        
        # Step 4: Resize while maintaining aspect ratio
        h, w = sharpened.shape
        aspect = w / h
        
        if aspect > output_size[0] / output_size[1]:
            new_w = output_size[0]
            new_h = int(new_w / aspect)
        else:
            new_h = output_size[1]
            new_w = int(new_h * aspect)
        
        resized = cv2.resize(sharpened, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
        self.steps.append(('06_resized', resized.copy()))
        
        # Step 5: Add padding to reach desired size
        result = np.ones((output_size[1], output_size[0]), dtype=np.uint8) * 255
        y_offset = (output_size[1] - new_h) // 2
        x_offset = (output_size[0] - new_w) // 2
        result[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = resized
        
        print(f"✓ Resized and padded: {output_size[0]}x{output_size[1]}px")
        self.steps.append(('07_final_grayscale', result.copy()))
        
        # Convert grayscale to BGR for model input
        final_bgr = cv2.cvtColor(result, cv2.COLOR_GRAY2BGR)
        self.steps.append(('08_final_bgr', final_bgr.copy()))
        
        # Save steps if requested
        if save_steps and output_dir:
            os.makedirs(output_dir, exist_ok=True)
            base_name = os.path.splitext(os.path.basename(image_path))[0]
            
            for step_name, step_img in self.steps:
                output_path = os.path.join(output_dir, f"{base_name}_{step_name}.png")
                cv2.imwrite(output_path, step_img)
            
            print(f"✓ Saved {len(self.steps)} preprocessing steps")
        
        preprocessing_time = time.time() - preprocessing_start
        print(f"✓ Preprocessing completed in {preprocessing_time:.2f}s")
        print(f"{'='*60}\n")
        
        return final_bgr, preprocessing_time

# ============================================================================
# PNDF EXTRACTION
# ============================================================================

class PNDFExtractor:
    """Extract drug names using PNDF-focused prompts"""
    
    @staticmethod
    def get_prompt() -> str:
        return """You are a medical OCR engine. Extract only the drug names from this prescription. 
Output format: plain comma-separated list. Exclude: all numbers, units (mg/ml/tabs), 
dosages, frequencies (BID/daily), and all instructions. Return only the drug names."""
    
    @staticmethod
    def parse_drug_names(text: str) -> List[str]:
        """Clean and parse drug names from output"""
        drugs = re.split(r'[,;\n]', text)
        cleaned = [drug.strip() for drug in drugs if drug.strip()]
        return cleaned

# ============================================================================
# OCR PIPELINE WITH CPU FIX
# ============================================================================

class EnhancedPrescriptionOCR:
    """Complete pipeline with optimized preprocessing and metrics"""
    
    def __init__(self, base_model: str, adapter_path: str):
        print("🔹 Initializing Enhanced Prescription OCR...")
        print(f"📁 Working directory: {TUNING_DIR}")
        
        # Detect device
        if torch.cuda.is_available():
            self.device = "cuda"
            dtype = torch.bfloat16
            use_device_map = True
            print(f"✓ Using CUDA GPU: {torch.cuda.get_device_name(0)}")
            print(f"  GPU Memory: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")
        else:
            self.device = "cpu"
            dtype = torch.float32
            use_device_map = False  # CPU FIX: Disable device_map
            print("⚠️  No CUDA GPU detected - using CPU")
            print("  ⏱️  Inference will be slower (3-10 min per image)")
            print("  💡 For faster inference, use a CUDA-enabled GPU")
        
        print(f"\n🔄 Loading model (this may take 2-3 minutes on CPU)...")
        load_start = time.time()
        
        # Load model differently based on device
        if use_device_map:
            # GPU: Use device_map
            print("  Loading with device_map for GPU...")
            self.model = Qwen2VLForConditionalGeneration.from_pretrained(
                base_model,
                torch_dtype=dtype,
                device_map="auto",
                low_cpu_mem_usage=True
            )
        else:
            # CPU: Load directly without device_map (FIX)
            print("  Loading directly to CPU (no device_map)...")
            self.model = Qwen2VLForConditionalGeneration.from_pretrained(
                base_model,
                torch_dtype=dtype,
                low_cpu_mem_usage=True
            )
            print("  Moving model to CPU...")
            self.model = self.model.to("cpu")
        
        print(f"✓ Base model loaded ({time.time() - load_start:.1f}s)")
        
        # Load adapter if available
        if adapter_path and os.path.exists(adapter_path):
            print(f"  Loading adapter from: {adapter_path}")
            adapter_start = time.time()
            
            try:
                self.model = PeftModel.from_pretrained(
                    self.model, 
                    adapter_path,
                    device_map=None if not use_device_map else "auto"  # CPU FIX
                )
                print(f"✓ Adapter loaded ({time.time() - adapter_start:.1f}s)")
            except Exception as e:
                print(f"⚠️  Adapter loading failed: {e}")
                print("  Continuing with base model only...")
        else:
            print(f"⚠️  Adapter not found: {adapter_path}")
            print("  Using base model only...")
        
        self.model.eval()
        
        load_time = time.time() - load_start
        print(f"✅ Model loaded in {load_time:.1f}s")
        
        self.processor = AutoProcessor.from_pretrained(base_model)
        self.preprocessor = LightweightPreprocessor()
        self.extractor = PNDFExtractor()
        self.metrics_calculator = OCRMetrics()
        
        print("✅ Ready\n")
    
    def extract(self, 
                image_path: str,
                use_preprocessing: bool = True,
                save_steps: bool = True,
                ground_truth: Optional[str] = None,
                ground_truth_list: Optional[List[str]] = None) -> Dict:
        """Extract drug names from prescription with optional evaluation"""
        
        total_start = time.time()
        result = {'image': os.path.basename(image_path)}
        
        # Preprocessing
        preprocessing_time = 0
        if use_preprocessing:
            print("🔄 Applying lightweight preprocessing...")
            output_steps = os.path.join(OUTPUT_DIR, 'steps') if save_steps else None
            processed, preprocessing_time = self.preprocessor.preprocess_image(
                image_path,
                output_size=(1024, 1024),
                save_steps=save_steps,
                output_dir=output_steps
            )
            
            temp_path = os.path.join(OUTPUT_DIR, f"{os.path.splitext(os.path.basename(image_path))[0]}_processed.png")
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            cv2.imwrite(temp_path, processed)
            image_to_use = temp_path
            result['processed_image'] = temp_path
            print(f"💾 Saved preprocessed image: {temp_path}\n")
        else:
            image_to_use = image_path
            result['processed_image'] = None
        
        # Inference
        prompt = self.extractor.get_prompt()
        messages = [{
            "role": "user",
            "content": [
                {"type": "image", "image": image_to_use},
                {"type": "text", "text": prompt}
            ],
        }]
        
        print("🤖 Running OCR inference...")
        if self.device == "cpu":
            print("   ⏱️  This may take 3-10 minutes on CPU...")
        
        inference_start = time.time()
        
        text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = self.processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        ).to(self.model.device)
        
        generation_start = time.time()
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=50,
                temperature=0.1,
                do_sample=False,
                num_beams=1
            )
        generation_time = time.time() - generation_start
        
        generated_ids = [
            output_ids[len(input_ids):] 
            for input_ids, output_ids in zip(inputs.input_ids, outputs)
        ]
        raw_output = self.processor.batch_decode(
            generated_ids, 
            skip_special_tokens=True, 
            clean_up_tokenization_spaces=False
        )[0].strip()
        
        inference_time = time.time() - inference_start
        total_time = time.time() - total_start
        drug_names = self.extractor.parse_drug_names(raw_output)
        
        result.update({
            'raw_output': raw_output,
            'drug_names': drug_names,
            'timing': {
                'preprocessing_time': preprocessing_time,
                'inference_time': inference_time,
                'generation_time': generation_time,
                'total_time': total_time
            }
        })
        
        print(f"✅ Complete")
        print(f"\n⏱️  TIMING BREAKDOWN:")
        print(f"   Preprocessing: {preprocessing_time:.2f}s")
        print(f"   Inference: {inference_time:.2f}s")
        print(f"   - Generation: {generation_time:.2f}s")
        print(f"   Total: {total_time:.2f}s")
        print(f"\n📋 Extracted drugs: {', '.join(drug_names) if drug_names else 'None'}\n")
        
        # Calculate metrics if ground truth is provided
        if ground_truth and JIWER_AVAILABLE:
            print(f"\n{'─'*60}")
            print("📊 CALCULATING METRICS (WER)")
            print(f"{'─'*60}")
            wer_metrics = self.metrics_calculator.calculate_wer(ground_truth, raw_output)
            result['wer_metrics'] = wer_metrics
            
            if 'error' not in wer_metrics:
                print(f"  Word Error Rate (WER): {wer_metrics['wer_percentage']:.2f}%")
                print(f"  Substitutions: {wer_metrics['substitutions']}")
                print(f"  Deletions: {wer_metrics['deletions']}")
                print(f"  Insertions: {wer_metrics['insertions']}")
                print(f"  Hits: {wer_metrics['hits']}")
        
        if ground_truth_list:
            print(f"\n{'─'*60}")
            print("📊 CALCULATING METRICS (Accuracy)")
            print(f"{'─'*60}")
            accuracy_metrics = self.metrics_calculator.calculate_accuracy(ground_truth_list, drug_names)
            result['accuracy_metrics'] = accuracy_metrics
            
            print(f"  Precision: {accuracy_metrics['precision_percentage']:.2f}%")
            print(f"  Recall: {accuracy_metrics['recall_percentage']:.2f}%")
            print(f"  F1 Score: {accuracy_metrics['f1_percentage']:.2f}%")
            print(f"  Exact Match: {'✓' if accuracy_metrics['exact_match'] else '✗'}")
            print(f"\n  Correctly Identified: {accuracy_metrics['correctly_identified']}")
            print(f"  Missed: {accuracy_metrics['missed_drugs']}")
            print(f"  False Detections: {accuracy_metrics['false_detections']}")
        
        print()
        return result
    
    def compare_with_evaluation(self, image_path: str) -> Dict:
        """Compare with/without preprocessing and evaluate with ground truth"""
        
        comparison_start = time.time()
        
        print(f"\n{'='*60}")
        print(f"🔬 COMPARISON TEST WITH EVALUATION")
        print(f"📄 Image: {os.path.basename(image_path)}")
        print(f"{'='*60}\n")
        
        # Get ground truth from user
        print("📝 Please enter the ground truth:")
        print("\n1️⃣  Enter the FULL TEXT ground truth (for WER calculation):")
        print("   Example: Amoxicillin 500mg, Paracetamol 500mg, Ibuprofen 200mg")
        ground_truth_text = input("   Ground Truth Text: ").strip()
        
        print("\n2️⃣  Enter the DRUG NAMES ONLY (comma-separated, for accuracy):")
        print("   Example: Amoxicillin, Paracetamol, Ibuprofen")
        ground_truth_drugs_input = input("   Ground Truth Drugs: ").strip()
        ground_truth_drugs = [drug.strip() for drug in ground_truth_drugs_input.split(',') if drug.strip()]
        
        print(f"\n{'─'*60}\n")
        
        results = {
            'image': os.path.basename(image_path), 
            'ground_truth': {
                'text': ground_truth_text,
                'drugs': ground_truth_drugs
            },
            'tests': []
        }
        
        # Test 1: No preprocessing
        print(f"{'─'*60}")
        print(f"TEST 1: RAW IMAGE (No Preprocessing)")
        print(f"{'─'*60}")
        raw_result = self.extract(
            image_path, 
            use_preprocessing=False, 
            save_steps=False,
            ground_truth=ground_truth_text if ground_truth_text else None,
            ground_truth_list=ground_truth_drugs if ground_truth_drugs else None
        )
        raw_result['test_name'] = "Raw"
        results['tests'].append(raw_result)
        
        # Test 2: With lightweight preprocessing
        print(f"{'─'*60}")
        print(f"TEST 2: LIGHTWEIGHT PREPROCESSING")
        print(f"{'─'*60}")
        processed_result = self.extract(
            image_path, 
            use_preprocessing=True, 
            save_steps=True,
            ground_truth=ground_truth_text if ground_truth_text else None,
            ground_truth_list=ground_truth_drugs if ground_truth_drugs else None
        )
        processed_result['test_name'] = "Preprocessed"
        results['tests'].append(processed_result)
        
        comparison_time = time.time() - comparison_start
        results['total_comparison_time'] = comparison_time
        
        # Summary
        print(f"\n{'='*60}")
        print(f"📊 COMPARISON RESULTS")
        print(f"{'='*60}\n")
        
        print(f"  Ground Truth Drugs: {', '.join(ground_truth_drugs)}\n")
        
        for test in results['tests']:
            drugs = ', '.join(test['drug_names']) if test['drug_names'] else "None detected"
            print(f"  {test['test_name']:15s} → {drugs}")
            print(f"  {'':15s}   Processing time: {test['timing']['total_time']:.2f}s")
            
            if 'wer_metrics' in test and 'error' not in test['wer_metrics']:
                print(f"  {'':15s}   WER: {test['wer_metrics']['wer_percentage']:.2f}%")
            
            if 'accuracy_metrics' in test:
                print(f"  {'':15s}   Precision: {test['accuracy_metrics']['precision_percentage']:.2f}%")
                print(f"  {'':15s}   Recall: {test['accuracy_metrics']['recall_percentage']:.2f}%")
                print(f"  {'':15s}   F1: {test['accuracy_metrics']['f1_percentage']:.2f}%")
            print()
        
        print(f"  Total comparison time: {comparison_time:.2f}s")
        
        # Save results
        output_file = os.path.join(OUTPUT_DIR, 'comparison_with_metrics.json')
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2)
        
        print(f"\n✅ Results saved: {output_file}")
        print(f"\n{'='*60}\n")
        
        return results

# ============================================================================
# MAIN
# ============================================================================

def main():
    """Run pipeline on prescription image with evaluation"""
    
    # System info
    print(f"\n{'='*60}")
    print("🔍 SYSTEM CHECK")
    print(f"{'='*60}")
    print(f"PyTorch version: {torch.__version__}")
    print(f"CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"CUDA device: {torch.cuda.get_device_name(0)}")
        print(f"CUDA memory: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")
    else:
        print("Device: CPU only")
    print(f"{'='*60}\n")
    
    # Target image
    TEST_IMAGE = os.path.join(TUNING_DIR, "img9.png")
    
    if not os.path.exists(TEST_IMAGE):
        print(f"❌ Image not found: {TEST_IMAGE}")
        print(f"\n📁 Current directory: {TUNING_DIR}")
        
        # List available images
        images = [f for f in os.listdir(TUNING_DIR) 
                 if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
        if images:
            print(f"\n📷 Available images:")
            for img in images:
                print(f"  • {img}")
        return
    
    print(f"✅ Found target image: {TEST_IMAGE}")
    print(f"📂 Output directory: {OUTPUT_DIR}\n")
    
    if not JIWER_AVAILABLE:
        print("⚠️  WARNING: jiwer not installed. WER metrics will not be available.")
        print("   Install with: pip install jiwer\n")
    
    # Initialize OCR system
    ocr = EnhancedPrescriptionOCR(BASE_MODEL, ADAPTER_PATH)
    
    # Run comparison with evaluation
    results = ocr.compare_with_evaluation(TEST_IMAGE)
    
    # Final summary
    print("\n" + "="*60)
    print("✨ PROCESSING COMPLETE!")
    print("="*60)
    print(f"\n⏱️  TOTAL TIME: {results['total_comparison_time']:.2f}s")
    print(f"\n📂 Output structure:")
    print(f"   {OUTPUT_DIR}/")
    print(f"   ├── comparison_with_metrics.json  # Results with WER & Accuracy")
    print(f"   ├── 1000000576_processed.png     # Final preprocessed image")
    print(f"   └── steps/                        # 8 preprocessing steps")
    print("\n" + "="*60 + "\n")

if __name__ == "__main__":
    main()
