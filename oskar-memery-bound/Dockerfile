# Uses the official uv image so `uv sync` reproduces the locked deps exactly.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

# Install dependencies first (cached unless the lockfile changes).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Then the application code.
COPY image.py ./

ENV DATA_DIR=/data \
    PORT=8080
EXPOSE 8080
VOLUME ["/data"]

CMD ["uv", "run", "--no-dev", "image.py"]
