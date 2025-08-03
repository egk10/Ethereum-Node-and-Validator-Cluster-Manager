# Ethereum Node and Validator Cluster Manager - Docker Image
# Multi-stage build for different release types

# Base stage with Python and common dependencies
FROM python:3.11-slim as base

LABEL maintainer="egk10" \
      description="Ethereum Node and Validator Cluster Manager" \
      version="1.0.0"

# Install system dependencies
RUN apt-get update && apt-get install -y \
    openssh-client \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create app user
RUN useradd -m -u 1000 ethmanager

WORKDIR /app

# Copy core files
COPY requirements.txt .
COPY eth_validators/ eth_validators/
COPY README.md .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Set ownership
RUN chown -R ethmanager:ethmanager /app
USER ethmanager

# Core release (default)
FROM base as core
LABEL release.type="core"
# Already has everything needed for core

# Standard release  
FROM base as standard
LABEL release.type="standard"
COPY requirements.txt requirements-standard.txt
RUN pip install --no-cache-dir pandas

# Monitoring release
FROM standard as monitoring
LABEL release.type="monitoring"
COPY cluster-monitoring.yml setup-*.sh ./
RUN pip install --no-cache-dir prometheus-client

# Full release (with AI)
FROM monitoring as full
LABEL release.type="full"
COPY requirements-ml.txt .
RUN pip install --no-cache-dir -r requirements-ml.txt

# Default to core
FROM core as final

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python3 -m eth_validators --help > /dev/null || exit 1

# Entry point
ENTRYPOINT ["python3", "-m", "eth_validators"]
CMD ["--help"]
