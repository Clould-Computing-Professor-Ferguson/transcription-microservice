# Use a lightweight Python image
FROM python:3.11-slim

# Create and switch to a working directory
WORKDIR /app

# Install system dependencies (only what's actually useful here)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Env tweaks
ENV PYTHONUNBUFFERED=1

# Cloud Run sets $PORT; default to 8080 for local runs
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
