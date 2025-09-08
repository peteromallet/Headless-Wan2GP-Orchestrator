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

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project (needed for shared modules)
COPY . .

# Create non-root user for security
RUN useradd -m -u 1000 apiworker && chown -R apiworker:apiworker /app
USER apiworker

# Health check for Railway
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import httpx; import asyncio; asyncio.run(httpx.AsyncClient().get('http://localhost:8080/health', timeout=5))" || exit 1

# Expose port for Railway (if needed for health checks)
EXPOSE 8080

# Default command - runs the API orchestrator in continuous mode
CMD ["python", "-m", "api_orchestrator.main"]
