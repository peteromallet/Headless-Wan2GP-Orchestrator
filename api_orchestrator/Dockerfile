# Railway-optimized Dockerfile for API Orchestrator
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy requirements from parent directory and install dependencies
COPY ../requirements.txt .
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project from parent directory (needed for shared modules)
COPY .. .

# Create non-root user for security
RUN useradd -m -u 1000 apiworker && chown -R apiworker:apiworker /app
USER apiworker

# Default command - runs the API orchestrator in continuous mode
CMD ["python", "-m", "api_orchestrator.main"]
