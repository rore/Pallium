FROM python:3.12-slim

WORKDIR /app

# System dependencies for native extensions (onnxruntime, tokenizers, usearch)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy project files (.dockerignore excludes .venv, .git, data, etc.)
COPY . .

# Install Pallium with vector and MCP dependencies
# huggingface-hub is needed for build-time model download (not in extras)
RUN pip install --no-cache-dir ".[vector,mcp]" huggingface-hub

# Build-time config for embedding model download (intfloat/multilingual-e5-small).
# pallium.docker.toml was copied as pallium.local.toml by COPY . . above,
# but it's named pallium.docker.toml — rename it so the config loader finds it.
RUN cp pallium.docker.toml pallium.local.toml && \
    python -m app.run download-embedding-model

EXPOSE 8000

ENTRYPOINT ["bash", "-c", "mkdir -p /tmp/pallium && exec python -m app.supervisor --host 0.0.0.0 --port 8000 --processors ${PALLIUM_PROCESSORS:-2} --cleaners ${PALLIUM_CLEANERS:-1}"]
