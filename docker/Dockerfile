# ****************************************************************
# STAGE : Base Python Image
# ****************************************************************
ARG PYTHON_VER=3.14
FROM docker.io/python:${PYTHON_VER}-slim AS base

ENV PYTHONUNBUFFERED=1

ENV PATH="${PATH}:/root/.local/bin:/root/.cargo/bin" \
    PROMETHEUS_MULTIPROC_DIR="/prom_shared"

RUN groupadd -r -g 1000 styrmin && useradd --no-log-init -u 1000 --home-dir /opt/styrmin -r -g styrmin styrmin

RUN mkdir /prom_shared /remote && chown styrmin:styrmin /prom_shared /remote

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install --no-install-recommends -y curl git pkg-config build-essential ca-certificates && \
    curl -sSL https://astral.sh/uv/install.sh | sh - && \
    apt-get autoremove -y && \
    apt-get clean all && \
    rm -rf /var/lib/apt/lists/*

# ****************************************************************
# STAGE : Frontend Build
# ****************************************************************
FROM docker.io/node:22-slim AS frontend

WORKDIR /frontend
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

# ****************************************************************
# STAGE : Backend
# ****************************************************************
FROM base

WORKDIR /source

# --------------------------------------------
# Install Dependencies
#   Copy in only pyproject.toml/uv.lock to help with caching this layer if no updates to dependencies
# --------------------------------------------
COPY uv.lock pyproject.toml ./
COPY backend ./backend
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-install-project
RUN uv pip install -e .

# --------------------------------------------
# Copy in the rest of the source code and install the project
# --------------------------------------------
# RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen

COPY --from=frontend /frontend/dist /source/frontend/dist

ENV PATH="/source/.venv/bin:$PATH"

# Copy example drivers into the image (docker-compose overrides this with a bind mount)
COPY driver/examples /styrmin/drivers
