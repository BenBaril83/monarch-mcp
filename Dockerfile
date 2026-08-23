# syntax=docker/dockerfile:1
FROM python:3.13-slim

# git is required at build time to resolve the git-pinned monarchmoneycommunity
# dependency (see [tool.uv.sources] in pyproject.toml)
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY server.py ./

RUN uv sync --no-dev

RUN useradd --create-home --uid 1000 monarch \
    && chown -R monarch:monarch /app
USER monarch

ENV PYTHONUNBUFFERED=1 \
    MONARCH_SESSION_DIR=/home/monarch/.monarch-mcp \
    MCP_TRANSPORT=http \
    HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000

CMD ["uv", "run", "--no-dev", "python", "server.py"]
