# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm AS builder

# Install uv for fast, reliable package installation
COPY --from=ghcr.io/astral-sh/uv:0.5.26 /uv /uvx /bin/

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Install dependencies first for maximum layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy project source and build package
COPY . .
RUN uv sync --frozen --no-dev

# ==============================================================================
# Final Runtime Stage
# ==============================================================================
FROM python:3.12-slim-bookworm AS runner

# Security: Create non-root user and group
RUN groupadd -g 1000 quantix && \
    useradd -u 1000 -g quantix -m -s /bin/bash quantix

WORKDIR /app

# Copy application virtual environment and code from builder
COPY --from=builder --chown=quantix:quantix /app /app

# Create dedicated directory for SQLite database volume
RUN mkdir -p /data && chown -R quantix:quantix /data

# Configure environment
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV DB_PATH=/data/quantix.db
ENV MCP_TRANSPORT=streamable-http
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8000

# Expose HTTP port
EXPOSE 8000

# Switch to unprivileged user
USER quantix

# Health check using standard Python urllib (no curl dependency required)
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').getcode() == 200 else 1)" || exit 1

# Entrypoint starts Quantix server
CMD ["python", "-m", "quantix.server"]

