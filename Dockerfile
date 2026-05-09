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

# Version stamp baked at build time. Empty for local builds; CI passes
# both via --build-arg (GIT_SHA always; GIT_TAG only when the build was
# triggered by a tag push). Placed AFTER collectstatic so changing the
# version doesn't invalidate the heavy layers.
ARG GIT_SHA=""
ARG GIT_TAG=""
ENV GIT_SHA=$GIT_SHA \
    GIT_TAG=$GIT_TAG

EXPOSE 3000


CMD ["gunicorn", "gitgrit.wsgi", "--bind", "0.0.0.0:3000", "--workers", "2", "--access-logfile", "-"]
