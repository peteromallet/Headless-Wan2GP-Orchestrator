# Railway Dockerfile for GPU Orchestrator
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Install common Python packages that are likely needed
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    httpx \
    asyncio \
    python-dotenv \
    supabase \
    requests \
    runpod \
    paramiko \
    aiohttp \
    structlog \
    python-json-logger \
    pydantic

# Copy the current directory (gpu_orchestrator)
COPY . /app/gpu_orchestrator/

# Copy main files to root level
COPY main.py /app/
COPY control_loop.py /app/gpu_orchestrator/
COPY database.py /app/gpu_orchestrator/
COPY runpod_client.py /app/gpu_orchestrator/
COPY logging_config.py /app/gpu_orchestrator/

# Create non-root user for security
RUN useradd -m -u 1000 orchestrator && chown -R orchestrator:orchestrator /app
USER orchestrator

# Default command - runs the GPU orchestrator in continuous mode
CMD ["python", "-m", "gpu_orchestrator.main", "continuous"]
