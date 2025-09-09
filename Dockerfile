# Multi-service Dockerfile for Railway
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project
COPY . .

# Create non-root user for security
RUN useradd -m -u 1000 worker && chown -R worker:worker /app
USER worker

# Create a startup script that detects the service type
COPY <<EOF /app/startup.sh
#!/bin/bash
if [ "\$RAILWAY_SERVICE_NAME" = "gpu-orchestrator" ]; then
    echo "Starting GPU Orchestrator..."
    exec python -m gpu_orchestrator.main continuous
elif [ "\$RAILWAY_SERVICE_NAME" = "api-orchestrator" ]; then
    echo "Starting API Orchestrator..."
    exec python -m api_orchestrator.main
else
    echo "Unknown service: \$RAILWAY_SERVICE_NAME"
    echo "Available services: api-orchestrator, gpu-orchestrator"
    exit 1
fi
EOF

RUN chmod +x /app/startup.sh

# Use the startup script as the default command
CMD ["/app/startup.sh"]
