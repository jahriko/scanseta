// Configuration validation and utilities

export const config = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL || '',
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

// Log configuration on app start (always log to help with debugging)
console.log('=== Configuration ===');
console.log('Environment:', import.meta.env.MODE);
console.log('API Base URL:', config.apiBaseUrl || '(not set)');
console.log('All env vars:', Object.keys(import.meta.env).filter(k => k.startsWith('VITE_')));

const validation = validateConfig();
if (!validation.valid) {
  console.error('❌ Configuration errors:');
  validation.errors.forEach(error => console.error(`  - ${error}`));
} else {
  console.log('✅ Configuration is valid');
}
console.log('====================');

