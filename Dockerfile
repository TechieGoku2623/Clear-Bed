# ClearBed API and UI image.
# Models, the warehouse, and Chroma are mounted at runtime so this image
# does not need a Synthea generate during build.
FROM python:3.11-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv

WORKDIR /app
ENV PYTHONPATH=/app/src \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:${PATH}"

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY app ./app
COPY knowledge ./knowledge
RUN uv sync --frozen --no-dev --group core --group ml --group agent --group api --group ui

EXPOSE 8000 8501
CMD ["uvicorn", "clearbed.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
