// Configuration validation and utilities

export const config = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL || '',
  defaultScanMode: import.meta.env.VITE_DEMO_MODE === 'false' ? 'live' : 'demo',
} as const;

export const validateConfig = (): { valid: boolean; errors: string[] } => {
  const errors: string[] = [];

  if (!config.apiBaseUrl) {
    errors.push('VITE_API_BASE_URL is not set. Please configure your backend API URL.');
  }

  if (config.apiBaseUrl && !config.apiBaseUrl.startsWith('http')) {
    errors.push('VITE_API_BASE_URL must start with http:// or https://');
  }

  if (config.apiBaseUrl && config.apiBaseUrl.endsWith('/')) {
    errors.push('VITE_API_BASE_URL should not end with a trailing slash');
  }

  return {
    valid: errors.length === 0,
    errors,
  };
};


