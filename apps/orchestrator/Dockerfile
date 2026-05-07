FROM python:3.11-slim AS base

# Azure Speech SDK native deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libssl-dev libasound2 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY audvoice ./audvoice

ENV PORT=8080
EXPOSE 8080

CMD ["uvicorn", "audvoice.main:app", "--host", "0.0.0.0", "--port", "8080", "--ws-max-size", "33554432"]
