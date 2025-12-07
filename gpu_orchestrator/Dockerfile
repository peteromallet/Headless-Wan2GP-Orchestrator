# GPU Orchestrator Dockerfile - Updated
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app

RUN apt-get update && apt-get install -y \
    curl \
    git \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements file
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project as a package
COPY . /app/gpu_orchestrator/

RUN useradd -m -u 1000 worker && chown -R worker:worker /app
USER worker

# Run GPU orchestrator as a module
CMD ["python", "-m", "gpu_orchestrator.main", "continuous"]