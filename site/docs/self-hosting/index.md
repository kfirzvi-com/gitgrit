# Self-Hosting GitGrit

GitGrit ships a fully self-contained deployment for organisations that
can't or won't run on the gitgrit.dev cloud. The same product runs
inside a closed network — no internet egress at install or at runtime —
connected to your own self-hosted GitLab over your own TLS chain.

This section walks you through scoping, building, installing, and
running a self-hosted GitGrit instance.

## Cloud or self-hosted?

For most teams the [gitgrit.dev cloud product](../getting-started/quickstart.md)
is the right choice — it's faster to start, gets updates automatically,
and there's nothing to operate. Self-hosting makes sense when **any** of
these apply:

- You need to keep source-code-aware tooling inside your network for
  compliance (FedRAMP, IL4/5, regulated finance, defence).
- Your VCS is self-hosted GitLab on an air-gapped network.
- Data residency forbids sending repository metadata to a third-party
  cloud.
- You want an offline-installable artifact you can ship across an
  approval boundary and reproduce later from a known SHA.

If none of those apply, stay on cloud — you'll get faster releases and
no install/upgrade overhead.

## What you're installing

A single bundle tarball produced by `scripts/build-airgap-bundle.sh` on
an internet-connected machine, containing:

- `gitgrit-app:<TAG>` — the Django app image, GIT_SHA-stamped at build time
- `gitgrit-sandbox:<TAG>` — the gVisor-isolated policy execution image
- `postgres:15` — the database
- `docker-compose.full.yaml` — the self-contained compose recipe
- `.env.example` — operator-fillable environment template
- Offline copies of these install docs

Everything else (DNS resolver, OAuth provider, CA bundle, NTP) you
already have in your network.

## The install flow at a glance

```
┌─ Build machine ─────────────┐    ┌─ Air-gap host ──────────────────┐
│ (one-time, has internet)    │    │                                  │
│                             │    │                                  │
│  build-airgap-bundle.sh ──► │.tgz│──► tar xzf + docker load          │
│                             │    │  + place CA bundle               │
│                             │    │  + fill .env                     │
│                             │    │  + docker compose up             │
│                             │    │  + airgap_setup + smoketest      │
│                             │    │  + createsuperuser + first login │
└─────────────────────────────┘    └──────────────────────────────────┘
```

End-to-end takes ~30 minutes once you have the prerequisites in hand.
Most of that is one-time setup work (OAuth app, CA bundle, DNS); the
actual install is five commands.

## Prerequisites

You'll need both machines. The build machine is anything with internet
and Docker; the air-gap host is where GitGrit will live.

### Build machine (one-time, has internet)

- Docker 24+
- ~4 GB free disk for the bundle tarball

### Air-gap host

- Linux with Docker 24+ and Docker Compose v2
- **gVisor (`runsc`) pre-installed**. Without it the sandbox falls back
  to the default Docker runtime, which gives weaker isolation. Detailed
  install steps live in [Operations → gVisor](operations.md#gvisor-runsc).
- An internal DNS resolver the sandbox containers can reach
  (e.g. `10.0.0.53`). gVisor cannot use Docker's embedded DNS at
  `127.0.0.11`, so the sandbox needs a real resolver.
- **No default route to the public internet** (firewall, missing
  gateway, or VPC subnet with no NAT). The `airgap_smoketest
  --check-isolation` command verifies this at install time.
- An internal GitLab CE/EE instance the host can reach over HTTPS, with
  admin access for creating an OAuth application.
- Optional but recommended: a reverse proxy / load balancer terminating
  TLS in front of the app.

## What's next

When you're ready, head to [Installation](installation.md) for the
step-by-step walkthrough. Bookmark [Operations](operations.md) for
ongoing maintenance, the gotchas table, and the full environment
variable reference.

!!! note "Scope of this guide"
    The current self-hosting recipe is `docker compose` on a single
    Linux host. Kubernetes and Helm chart deliveries aren't shipped yet
    — when they are, they'll appear as sibling pages under this section.
