#!/bin/bash

# Start the Prescription Scanner API

echo "Starting Prescription Scanner API..."

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Set environment variables
export PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512

# Start the server
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1 --reload

# Note: Use --workers 1 for GPU to avoid model duplication
# Remove --reload for production
