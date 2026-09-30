FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./

RUN uv pip install --system -r pyproject.toml

COPY . .

EXPOSE 8000

# Web dashboard + API. The daily pipeline runs separately (GitHub Actions or "python main.py").
CMD uvicorn app.api:app --host 0.0.0.0 --port ${PORT:-8000}

