// API client for prescription scanner backend
import { config } from './config';

const API_BASE_URL = config.apiBaseUrl;

// TypeScript interfaces for API responses
export interface Medication {
  name: string;
  dosage: string;
  frequency: string;
  confidence: number;
}

export interface PrescriptionResponse {
  success: boolean;
  medications: Medication[];
  raw_text: string;
  processing_time: number;
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

