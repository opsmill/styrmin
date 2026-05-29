# ----- Stage 1: Base -----
ARG PYTHON_VER=3.12
FROM docker.io/python:${PYTHON_VER}-slim AS base

ENV PYTHONUNBUFFERED=1
ENV PATH="${PATH}:/root/.local/bin"

RUN groupadd -r -g 1000 app && useradd --no-log-init -u 1000 --home-dir /opt/app -r -g app app

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install --no-install-recommends -y curl ca-certificates && \
    curl -sSL https://astral.sh/uv/install.sh | sh - && \
    apt-get autoremove -y && \
    apt-get clean all && \
    rm -rf /var/lib/apt/lists/*

# ----- Stage 2: Application -----
FROM base

ARG APP_VERSION=0.1.0

WORKDIR /app

# Copy dependency specification first for layer caching
COPY pyproject.toml ./

# Bump version using the build ARG
RUN uv version ${APP_VERSION}

# Install dependencies (without the project itself, for caching)
RUN --mount=type=cache,target=/root/.cache/uv uv sync --no-install-project

# Copy source code
COPY simple_app/ ./simple_app/

# Install the project
RUN --mount=type=cache,target=/root/.cache/uv uv sync

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
USER 1000

# Split ENTRYPOINT (the uvicorn binary + app target) from CMD (the runtime
# flags) so a Kubernetes container-`args`-only override replaces just the flags
# while keeping the entrypoint — see 014-component-container-overrides. The
# effective default command is unchanged from the previous single-CMD form
# (`uvicorn simple_app.main:app --host 0.0.0.0 --port 8000`). In Styrmin
# deployments the chart's `values.yaml` supplies the default `args`, which
# shadows this CMD; the CMD is retained for standalone `docker run` use.
ENTRYPOINT ["uvicorn", "simple_app.main:app"]
CMD ["--host", "0.0.0.0", "--port", "8000"]
