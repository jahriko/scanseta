#!/usr/bin/env node

/**
 * Environment Configuration Checker
 * 
 * This script helps verify your environment configuration before deployment.
 * Run with: node check-env.js
 */

import { readFileSync, existsSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

console.log('🔍 Checking Environment Configuration...\n');

// Check for .env files
const envFiles = ['.env', '.env.local', '.env.production'];
let foundEnvFile = false;
let apiUrl = null;

for (const file of envFiles) {
  const path = join(__dirname, file);
  if (existsSync(path)) {
    console.log(`✅ Found ${file}`);
    foundEnvFile = true;
    
    // Try to read VITE_API_BASE_URL
    const content = readFileSync(path, 'utf-8');
    const match = content.match(/VITE_API_BASE_URL=(.+)/);
    if (match) {
      apiUrl = match[1].trim().replace(/["']/g, '');
      console.log(`   API URL: ${apiUrl}`);
    }
  }
}

if (!foundEnvFile) {
  console.log('⚠️  No .env files found');
  console.log('   Create a .env.local file with:');
  console.log('   VITE_API_BASE_URL=http://localhost:8000\n');
}

console.log('\n📋 Configuration Checklist:\n');

// Check API URL format
if (apiUrl) {
  const checks = [
    {
      name: 'API URL is set',
      pass: !!apiUrl,
      message: apiUrl ? `✅ ${apiUrl}` : '❌ Not set'
    },
    {
      name: 'Starts with http:// or https://',
      pass: apiUrl.startsWith('http://') || apiUrl.startsWith('https://'),
      message: apiUrl.startsWith('http://') || apiUrl.startsWith('https://') 
        ? '✅ Valid protocol' 
        : '❌ Must start with http:// or https://'
    },
    {
      name: 'No trailing slash',
      pass: !apiUrl.endsWith('/'),
      message: !apiUrl.endsWith('/') 
        ? '✅ No trailing slash' 
        : '⚠️  Has trailing slash (may cause issues)'
    },
    {
      name: 'Uses HTTPS (required for mobile)',
      pass: apiUrl.startsWith('https://'),
      message: apiUrl.startsWith('https://') 
        ? '✅ Uses HTTPS' 
        : '⚠️  Uses HTTP (will not work on mobile in production)'
    }
  ];

  checks.forEach(check => {
    console.log(`${check.message}`);
  });

  const allPassed = checks.every(c => c.pass);
  
  console.log('\n' + '='.repeat(50));
  if (allPassed) {
    console.log('✅ All checks passed! Configuration looks good.');
  } else {
    console.log('⚠️  Some checks failed. Please review the issues above.');
  }
  console.log('='.repeat(50));
} else {
  console.log('❌ VITE_API_BASE_URL is not set');
  console.log('\n📝 To fix this:');
  console.log('   1. Create a .env.local file in the project root');
  console.log('   2. Add: VITE_API_BASE_URL=https://your-backend-url.com');
  console.log('   3. Restart your development server');
}

console.log('\n📚 For deployment to Vercel:');
console.log('   1. Go to Vercel Dashboard → Settings → Environment Variables');
console.log('   2. Add VITE_API_BASE_URL with your backend URL');
console.log('   3. Select all environments (Production, Preview, Development)');
console.log('   4. Redeploy your application');
console.log('\n   See VERCEL_SETUP.md for detailed instructions.\n');

