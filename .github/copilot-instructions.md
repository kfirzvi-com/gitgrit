# GitGud — Copilot Instructions

GitGud is an open-source DevOps compliance and best practices enforcement platform designed to streamline, automate, and scale DevOps adoption across organizations.

## Project Overview

**Purpose:** Policy-as-code platform for automated DevOps compliance & best practices enforcement  
**Target Users:** CISOs, compliance teams, DevOps/platform teams, engineering management  
**Integration:** GitLab webhooks, real-time policy execution, compliance dashboards  
**License:** Open source

## Architecture

### Tech Stack - Backend
- **Runtime:** Node.js + TypeScript
- **API:** Express.js REST API
- **Database:** PostgreSQL with Drizzle ORM
- **Migrations:** Drizzle Kit
- **Configuration:** node-config (YAML-based)
- **Container:** Docker + Helm charts for k8s deployment

### Tech Stack - Frontend
- **Framework:** (Check package.json for specifics)
- **Container:** Nginx + Docker
- **Deployment:** Kubernetes via Helm

### Tech Stack - Django (Alternative Backend)
- **Framework:** Django 5.x
- **Purpose:** Alternative implementation of backend services
- **Status:** Currently on feature branch

### Development Environment
- **Orchestration:** Tilt (for local k8s dev)
- **Kubernetes:** Docker Desktop / kind / kubeadm
- **Tunneling:** ngrok for TLS to GitLab webhooks
- **Database:** PostgreSQL (local via Docker Compose or k8s)

### Key Directories
- `backend/` — Node.js/TypeScript backend with API, policies, database
- `frontend/` — Web UI for dashboards, policy management, compliance views
- `django/` — Alternative Django implementation
- `helm/` — Kubernetes Helm charts for deployment
- `docs/` — Documentation including deployment guides
- `tools/inject/` — Utilities for policy injection
- `migrations/` — Database migrations (Drizzle)

## Development Workflow

### Local Development Setup
```bash
# Install dependencies
(cd backend && npm i)
(cd frontend && npm i)

# Configure environment
cp .env.example .env
# Edit .env with your values

# Start Tilt (runs services in k8s)
tilt up

# Run migrations (after postgres is up)
npm run migration:migrate
npm run migration:seed
```

### Current Branch Context
- **Active branch:** `feature/replace-backend-with-django`
- **Default branch:** `main`
- Backend is being reimplemented in Django as an alternative to Node.js

### Common Commands
- `tilt up` — Start all services (frontend/backend local, others in k8s)
- `npm run migration:migrate` — Run database migrations
- `npm run migration:seed` — Seed database with example data
- Backend scripts defined in `backend/package.json`
- Frontend scripts defined in `frontend/package.json`

## Core Concepts

### Policy as Code
- Policies are version-controlled JavaScript handlers
- Metadata: goals, categorization, compliance mapping (SOC2, ISO 27001)
- Criteria: context-aware execution (events, branches, file paths, languages)
- Handlers: receive rich context (GitLab events, project details, integrations)

### Git-Driven Workflows
- GitLab webhook integration
- Triggered by push, merge request, tag creation
- Real-time policy execution and feedback

### Compliance & Analytics
- Real-time dashboards showing compliance posture
- Policy execution results across all projects
- KPI tracking: Best Practices, Resilience, Compliance

### Example Policies
- README exists, tests exist, code coverage >80%
- No secrets in code, approved dependencies only
- Branch protection, RBAC enforcement, audit logging
- Container vulnerability scanning, replicas configured

## Business Context

GitGud is a SaaS product under the kfirzvi.com umbrella, targeting enterprise DevOps/platform teams and compliance organizations.

**For business strategy, pricing, GTM:** Reference `kfirzvi-hq` repo (owner-only, confidential)

**Product Positioning:**
- Open-source foundation with enterprise features
- Targets regulated industries (finance, healthcare) needing SOC2/ISO compliance
- Self-hosted option for air-gapped environments
- Focus on "shift-left" security and compliance automation

## Multi-Repo Workspace

This repo is part of a VS Code multi-root workspace:
- **kfirzvi-hq** — Business operations (agents, knowledge base, templates) — CONFIDENTIAL
- **kfirzvi.com** — Company website (SvelteKit consultancy landing page)
- **gitgud** — This repository (DevOps compliance platform)

All live under `~/projects/kfirzvi.com/`

**When working on this repo:**
- Keep project-specific insights and technical decisions documented here
- Reference kfirzvi-hq only for high-level business context
- Don't expose sensitive business data from kfirzvi-hq in code or commits

## Always Commit & Push

After making any file changes, **always suggest committing and pushing** those changes. Don't let edits sit uncommitted. Propose a clear commit message and offer to run the git commands.

## Session Retrospectives

After significant development sessions, consider whether these instructions should be updated:
- New services or components added?
- Architecture patterns changed?
- New integrations or dependencies?
- Development workflow improvements?

If yes, update this file and commit the changes.
