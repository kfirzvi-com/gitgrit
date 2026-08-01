FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# The dependency environment lives OUTSIDE /app so the later `COPY . .`
# can never clobber it, and is first on PATH so `python`/`gunicorn` resolve
# to it at both build time (collectstatic) and run time (CMD).
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Install system dependencies for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

# Install the EXACT versions recorded in uv.lock. `--locked` asserts the
# lockfile is up to date with pyproject.toml and never re-resolves: an edited
# dependency spec without a matching `uv lock` fails the build instead of
# silently floating to a newer version (which is how litellm 1.92 and mcp 2.0
# shipped broken images). To change versions: `uv lock` and commit uv.lock.
COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --locked --no-dev

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
