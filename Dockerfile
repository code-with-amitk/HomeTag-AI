# Multi-Stage Build

# --------------------- STAGE 1: BUILD STAGE ---------------------
# Includes all the tools and source code needed to build the app.
FROM python:3.10-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# Set the working directory inside the container
WORKDIR /build  

RUN python -m venv "$VIRTUAL_ENV"

# Copy all the source code into this build container
COPY pyproject.toml README.md ./
COPY app ./app

RUN python -m pip install --no-cache-dir . \
    && python -m pip uninstall --yes pip setuptools

# ----------------- STAGE 2: PRODUCTION STAGE ---------------------
# We switch to a completely fresh image.
FROM python:3.10-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

RUN groupadd --system --gid 10001 hometag \
    && useradd --system --uid 10001 --gid hometag --no-create-home hometag

# CRITICAL STEP: Copy ONLY the compiled binary from the builder stage.
# Everything else (source code, build tools, caches) is left behind.
COPY --from=builder /opt/venv /opt/venv
COPY --chown=10001:10001 migrations ./migrations
COPY --chown=10001:10001 alembic.ini ./

EXPOSE 8000

USER 10001:10001

# Command to run the binary when the container starts
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
