# grader-web and grader-worker share this image; the compose file picks the command.
FROM python:3.13-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
# xmlsec for python3-saml; bubblewrap for the autograde sandbox (worker only, harmless on web).
RUN apt-get update && apt-get install -y --no-install-recommends \
      libxmlsec1-openssl libxmlsec1-dev pkg-config build-essential bubblewrap \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --all-extras --no-install-project
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
RUN uv sync --frozen --no-dev --all-extras
RUN useradd -r -u 10001 grader && mkdir -p /data/artifacts && chown -R grader:grader /data
USER grader
ENV PATH="/app/.venv/bin:$PATH" GRADER_ARTIFACT_DIR=/data/artifacts
EXPOSE 8000
CMD ["uvicorn", "grader.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
