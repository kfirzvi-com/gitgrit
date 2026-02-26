# GitGud — Claude Code Instructions

GitGud is an open-source DevOps compliance and best practices enforcement platform designed to streamline, automate, and scale DevOps adoption across organizations.

## Claude Code Notes

### Key Local Dev Commands
```bash
# Install dependencies
(cd backend && npm i)
(cd frontend && npm i)

# Configure environment
cp .env.example .env   # then edit with your values

# Start all services (frontend/backend local, others in k8s)
tilt up

# Run migrations (after postgres is up)
npm run migration:migrate
npm run migration:seed
```

### Current Branch Status
- **Active feature branch:** `feature/replace-backend-with-django`
- **Default branch:** `main`
- Backend is being reimplemented in Django as an alternative to the existing Node.js backend

## Project Overview

**Purpose:** Policy-as-code platform for automated DevOps compliance & best practices enforcement
**Target Users:** CISOs, compliance teams, DevOps/platform teams, engineering management
**Integration:** GitLab webhooks, real-time policy execution, compliance dashboards
**License:** Open source

## Architecture

### Tech Stack — Backend (Current: Node.js)
- **Runtime:** Node.js + TypeScript
- **API:** Express.js REST API
- **Database:** PostgreSQL with Drizzle ORM
- **Migrations:** Drizzle Kit
- **Configuration:** node-config (YAML-based)
- **Container:** Docker + Helm charts for k8s deployment

### Tech Stack — Frontend
- **Framework:** React 18 + Material UI (MUI)
- **Container:** Nginx + Docker
- **Deployment:** Kubernetes via Helm

### Tech Stack — Django (Alternative Backend)
- **Framework:** Django 5.x
- **Purpose:** Alternative implementation of backend services
- **Status:** In progress on `feature/replace-backend-with-django`

### Development Environment
- **Orchestration:** Tilt (for local k8s dev)
- **Kubernetes:** Docker Desktop / kind / kubeadm
- **Tunneling:** ngrok for TLS to GitLab webhooks
- **Database:** PostgreSQL (local via Docker Compose or k8s)

### Key Directories
- `backend/` — Node.js/TypeScript backend with API, policies, database
- `frontend/` — React 18 + MUI web UI
- `django/` — Alternative Django implementation
- `helm/` — Kubernetes Helm charts for deployment
- `docs/` — Documentation including deployment guides
- `tools/inject/` — Utilities for policy injection
- `migrations/` — Database migrations (Drizzle)

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

GitGud is an open-source DevOps compliance platform targeting enterprise DevOps/platform teams and compliance organizations.

**Product Positioning:**
- Open-source foundation with enterprise features
- Targets regulated industries (finance, healthcare) needing SOC2/ISO compliance
- Self-hosted option for air-gapped environments
- Focus on "shift-left" security and compliance automation

