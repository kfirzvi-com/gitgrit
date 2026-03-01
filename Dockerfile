FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN pip install uv && uv pip install --system -r pyproject.toml

COPY . .
RUN SECRET_KEY=build-only python manage.py collectstatic --noinput

EXPOSE 3000


CMD ["gunicorn", "gitgrit.wsgi", "--bind", "0.0.0.0:3000", "--workers", "2", "--access-logfile", "-"]
