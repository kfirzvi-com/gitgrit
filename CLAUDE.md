# GitGrit — Claude Code Instructions

GitGrit is a DevOps compliance and best practices enforcement platform designed to streamline, automate, and scale DevOps adoption across organizations.

## Local Dev Commands

```bash
# Start database
docker compose up -d

# Install dependencies
uv sync

# Run migrations
uv run python manage.py migrate

# Run dev server
uv run python manage.py runserver
```

## Architecture

### Tech Stack
- **Framework:** Django 6.x + django-allauth + django-htmx
- **Database:** PostgreSQL
- **Templates:** Django templates + HTMX + DaisyUI/Tailwind (CDN)
- **Sandbox:** gVisor-sandboxed Docker containers for policy execution
- **Deployment:** Kamal (Docker-based) to AWS VM

### Key Directories
- `gitgrit/` — Django settings package (settings, urls, wsgi, asgi)
- `app/` — Main Django app (models, views, templates, services)
- `app/templates/` — HTML templates (base, pages, components, partials)
- `app/presentation/` — Web views and URL routing
- `app/infrastructure/` — External integrations (sandbox runner, platform clients)
- `app/domain/` — Business logic and domain services
- `sandbox_image/` — Docker image for sandboxed policy execution
- `config/` — Kamal deployment configuration

## Core Concepts

### Policy as Code
- Policies are version-controlled Python scripts
- Executed in gVisor-sandboxed Docker containers
- Support GitHub and GitLab integrations

### Multi-Tenant
- Workspace-based multi-tenancy
- Members, connections, projects, stacks, policies per workspace

## Deployment
- **Domain:** gitgrit.dev
- **Deployment tool:** Kamal (config in `config/deploy.yml`)
- **Production:** Gunicorn + WhiteNoise behind Kamal proxy
