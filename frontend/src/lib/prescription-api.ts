// API client for prescription scanner backend
import { config } from './config';

const API_BASE_URL = config.apiBaseUrl;

// TypeScript interfaces for API responses
export interface Medication {
  name: string;
  dosage?: string | null;
  quantity?: string | null;
  signa?: string | null;
  frequency?: string | null;
  confidence: number;
  original_name?: string | null;
  flags?: string[];
  match_method?: string | null;
  edit_distance?: number | null;
  similarity?: number | null;
  plausibility?: number | null;
}

export interface FDAMatch {
  registration_number?: string | null;
  generic_name?: string | null;
  brand_name?: string | null;
  dosage_strength?: string | null;
  classification?: string | null;
  details?: Record<string, string>;
}

export interface FDAVerificationItem {
  query: string;
  found: boolean;
  matches?: FDAMatch[];
  best_match?: FDAMatch | null;
  error?: string | null;
  error_code?: string | null;
  scraped_at?: string | null;
}

export interface PNDFEnrichmentItem {
  name: string;
  found: boolean;
  atc_code?: string | null;
  classification?: Record<string, string | null | undefined> | null;
  dosage_forms?: Array<Record<string, unknown>>;
  indications?: string | null;
  contraindications?: string | null;
  precautions?: string | null;
  adverse_reactions?: string | null;
  drug_interactions?: string | null;
  mechanism_of_action?: string | null;
  dosage_instructions?: string | null;
  administration?: string | null;
  pregnancy_category?: string | null;
  message?: string | null;
  error?: string | null;
  error_code?: string | null;
  scraped_at?: string | null;
}

export interface PrescriptionResponse {
  success: boolean;
  medications: Medication[];
  raw_text?: string;
  processing_time: number;
  doctor_name?: string | null;
  patient_name?: string | null;
  patient_sex?: string | null;
  patient_age?: string | null;
  date?: string | null;
  enriched?: PNDFEnrichmentItem[] | null;
  enriched_medications?: PNDFEnrichmentItem[] | null;
  fda_verification?: FDAVerificationItem[] | null;
  pndf_enriched?: PNDFEnrichmentItem[] | null;
  can_enrich?: boolean;
  enrichment_job_id?: string | null;
  enrichment_status?: string;
  fda_enrichment_status?: string | null;
  pndf_enrichment_status?: string | null;
  enrichment_updated_at?: string | null;
  enrichment_message?: string | null;
}

export interface EnrichmentJobStatusResponse {
  success: boolean;
  job_id: string;
  status: string;
  fda_status: string;
  pndf_status: string;
  drug_names: string[];
  fda_verification: FDAVerificationItem[];
  pndf_enriched: PNDFEnrichmentItem[];
  errors?: Record<string, string>;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  updated_at?: string | null;
  expires_at?: string | null;
  message?: string | null;
}

export interface HealthResponse {
  message: string;
  status: string;
  model_loaded: boolean;
  device?: string;
  cuda_available?: boolean;
}

export interface ModelLoadResponse {
  success: boolean;
  message: string;
  base_model: string;
  adapter_repo: string;
}

// API functions
export const getHealth = async (): Promise<HealthResponse> => {
  if (!API_BASE_URL) {
    throw new Error('API URL is not configured. Please set VITE_API_BASE_URL environment variable.');
  }
  
  try {
    const res = await fetch(`${API_BASE_URL}/health`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
    });
    
    if (!res.ok) {
      throw new Error(`Health check failed with status ${res.status}`);
    }
    return res.json();
  } catch (error) {
    if (error instanceof TypeError && error.message.includes('fetch')) {
      throw new Error('Cannot connect to server. Please check your network connection and API URL.');
    }
    throw error;
  }
};

export const loadModel = async (): Promise<ModelLoadResponse> => {
  if (!API_BASE_URL) {
    throw new Error('API URL is not configured. Please set VITE_API_BASE_URL environment variable.');
  }
  
  const params = new URLSearchParams({
    base_model: 'Qwen/Qwen2.5-VL-7B-Instruct',
    adapter_repo: 'Jahriko/prescription_model',
  });
  
  try {
    const res = await fetch(`${API_BASE_URL}/load-model?${params.toString()}`, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
      },
    });
    
    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      const errorMessage = errorData.detail || `Model load failed with status ${res.status}`;
      throw new Error(errorMessage);
    }
    return res.json();
  } catch (error) {
    if (error instanceof TypeError && error.message.includes('fetch')) {
      throw new Error('Cannot connect to server. Please check your network connection and API URL.');
    }
    throw error;
  }
};

export const scanPrescription = async (file: File): Promise<PrescriptionResponse> => {
  if (!API_BASE_URL) {
    throw new Error('API URL is not configured. Please set VITE_API_BASE_URL environment variable.');
  }
  
  const form = new FormData();
  form.append('file', file);
  
  try {
    const res = await fetch(`${API_BASE_URL}/scan`, {
      method: 'POST',
      body: form,
      headers: {
        'Accept': 'application/json',
      },
    });
    
    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      const errorMessage = errorData.detail || `Scan failed with status ${res.status}`;
      throw new Error(errorMessage);
    }
    return res.json();
  } catch (error) {
    if (error instanceof TypeError && error.message.includes('fetch')) {
      throw new Error('Cannot connect to server. Please check your network connection and API URL.');
    }
    throw error;
  }
};

export const getEnrichmentJobStatus = async (jobId: string): Promise<EnrichmentJobStatusResponse> => {
  if (!API_BASE_URL) {
    throw new Error('API URL is not configured. Please set VITE_API_BASE_URL environment variable.');
  }

  try {
    const res = await fetch(`${API_BASE_URL}/enrichment-jobs/${encodeURIComponent(jobId)}`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
    });

    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      const errorMessage = errorData.detail || `Enrichment status failed with status ${res.status}`;
      throw new Error(errorMessage);
    }
    return res.json();
  } catch (error) {
    if (error instanceof TypeError && error.message.includes('fetch')) {
      throw new Error('Cannot connect to server. Please check your network connection and API URL.');
    }
    throw error;
  }
};

