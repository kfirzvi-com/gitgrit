# Air-gapped GitGrit deployment

GitGrit can run inside a closed network with no internet access at install
or runtime, connected to a self-hosted GitLab over the customer's own TLS
chain. This document walks through building the bundle on an
internet-connected machine, shipping it across the air gap, and bringing
the stack up.

Cloud / hosted deployments do **not** use any of this — they continue to
use Kamal (`config/deploy.yml`). This guide is exclusive to air-gap.

---

## 1. Prerequisites

**Build machine** (one-time, has internet):
- Docker 24+
- ~4 GB free disk for the bundle tarball

**Air-gap host** (the customer-side server):
- Linux with Docker 24+ and Docker Compose v2
- **gVisor (`runsc`) pre-installed** — see "gVisor" below. Without it the
  sandbox falls back to the default Docker runtime, which is weaker
  isolation. The runner logs a warning when this happens.
- An internal DNS resolver the sandbox containers can reach (e.g.
  `10.0.0.53`)
- Optional: a reverse proxy / load balancer terminating TLS in front of
  the app

---

## 2. Build the bundle

On the internet-connected build machine, from a checkout of this repo:

```bash
./scripts/build-airgap-bundle.sh 1.0
```

Produces `gitgrit-install-1.0.tgz` containing:
- `gitgrit-bundle-1.0.tar` — `docker save` of `gitgrit-app:1.0`,
  `gitgrit-sandbox:1.0`, `postgres:15`
- `docker-compose.prod.yml`
- `.env.example`
- `docs/airgap.md` (this file)

Transfer the `.tgz` to the air-gap host by whatever channel is approved
(USB, internal SFTP, etc.).

---

## 3. Install on the air-gap host

```bash
tar xzf gitgrit-install-1.0.tgz
docker load -i gitgrit-bundle-1.0.tar     # loads all three images
cp .env.example .env
$EDITOR .env                              # fill in every blank
```

### 3a. The customer CA bundle

Place a PEM file at the path you set in `.env` as `CUSTOMER_CA_PATH`
(default `/opt/gitgrit/ca-bundle.pem`).

**The PEM must be the issuing CA chain that signed your internal GitLab's
TLS cert — not the GitLab server cert itself.** If your network has a
TLS-intercepting proxy, append that intercepting CA to the same file.
This trips ops teams more often than anything else; double-check.

Mounted read-only into the app container and any sandbox containers it
spawns. Used by:
- The app's `requests` library (via `REQUESTS_CA_BUNDLE`).
- The sandbox's `urllib` (via `SSL_CERT_FILE`).

### 3b. Bring the stack up

```bash
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml exec app \
    python manage.py airgap_setup
```

`airgap_setup` runs migrations, validates `SITE_URL` is a public hostname,
verifies the CA bundle is readable, and prunes `SocialApp` DB rows for any
provider you disabled. Idempotent — re-run any time you change a flag in
`.env`.

### 3c. Create the first admin user

```bash
docker compose -f docker-compose.prod.yml exec app \
    python manage.py createsuperuser
```

Then log in at `${SITE_URL}/admin/` and create your workspace, GitLab
OAuth `SocialApp`, and first `PlatformConnection` pointing at your
internal GitLab.

---

## 4. gVisor (`runsc`) on the air-gap host

Policy code runs in containers wrapped by gVisor to keep them isolated
from the host. Install `runsc` system-wide on the air-gap host before
bringing the stack up:

- gVisor offline-install instructions: see
  https://gvisor.dev/docs/user_guide/install/ (download the binary on the
  build machine; ship it alongside the bundle).
- After install, restart the Docker daemon. Verify with
  `docker info | grep runsc`.

If `runsc` is missing, the sandbox runner logs a warning and falls back
to the default Docker runtime. Policies still run, but the isolation
guarantees are weaker. Customers with strict security posture should
treat a missing `runsc` as a blocker.

---

## 5. Environment variable reference

| Var | Purpose |
|---|---|
| `TAG` | Image tag (matches the bundle version). |
| `SITE_URL` | Public hostname the customer's GitLab can reach for webhooks. Must not be `localhost`. |
| `APP_PORT` | Host port to expose the app on. Default `3000`. |
| `SECRET_KEY` | Django signing key. **Never rotate** after deploy — invalidates sessions and stored OAuth tokens. |
| `GITGRIT_ENCRYPTION_KEY` | Fernet key for OAuth-token-at-rest encryption. **Never rotate** for the same reason. |
| `POSTGRES_USER` / `_DB` / `_PASSWORD` | Database credentials. |
| `AUTH_PROVIDER_GITHUB_ENABLED` | `True` / `False` (exact strings). Air-gap default `False`. |
| `AUTH_PROVIDER_GITLAB_ENABLED` | `True` / `False`. Air-gap default `True`. |
| `AUTH_PROVIDER_GOOGLE_ENABLED` | `True` / `False`. Air-gap default `False`. |
| `GITLAB_URL` | Root URL of your internal GitLab, no trailing slash. |
| `GITLAB_CLIENT_ID` / `_SECRET` | OAuth app credentials from GitLab. Callback: `${SITE_URL}/accounts/gitlab/login/callback/` |
| `SANDBOX_DNS` | Comma-separated internal DNS resolvers. gVisor cannot use Docker's embedded DNS. |
| `CUSTOMER_CA_PATH` | Host path to the customer CA bundle PEM. |

`AIRGAPPED`, `SANDBOX_NETWORK`, `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`,
`DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` are set automatically by
`docker-compose.prod.yml` — operators should not override them.

---

## 6. Network topology

```
            ┌──────────────────── gitgrit_internal (bridge) ──────────────────┐
            │                                                                  │
            │   ┌─────────┐    ┌────────────────────┐    ┌──────────────────┐  │
            │   │  app    │    │  on-demand sandbox │    │  customer GitLab │  │
            │   │ (Django)│←──→│  (gVisor / runsc)  │←──→│ (out of stack)   │  │
            │   └────┬────┘    └────────────────────┘    └──────────────────┘  │
            │        │                                                          │
            │   ┌────▼────┐                                                     │
            │   │   db    │                                                     │
            │   │(postgres)                                                     │
            │   └─────────┘                                                     │
            └──────────────────────────────────────────────────────────────────┘
```

`SANDBOX_NETWORK=gitgrit_internal` in compose ties spawned sandbox
containers to the same bridge so they can resolve and reach the customer
GitLab on the same network (or routable from it).

> **One stack per host.** The `gitgrit_internal` bridge has a fixed name
> (so the sandbox runner can attach on-demand containers to a known
> network from outside compose). If you bring up a second GitGrit stack
> on the same host, both stacks share the bridge — and Docker DNS for
> `db` will resolve to *both* containers, with the app silently picking
> whichever's IP comes back first. Symptoms: the app logs
> `password authentication failed for user "gitgrit"` against an IP
> that doesn't match the stack it was supposed to talk to. If you need
> multiple installs on one host, tear down the previous stack first
> (`docker compose -f docker-compose.prod.yml down`) before bringing
> up the new one.

---

## 7. Time / NTP

Air-gap hosts with drifted clocks break TLS verification in non-obvious
ways ("cert not yet valid", "cert expired"). Point the host at your
internal NTP server before bringing up the stack.

---

## 8. Common ops

**Tail logs:**
```bash
docker compose -f docker-compose.prod.yml logs -f app
```

**Database backup:**
```bash
docker compose -f docker-compose.prod.yml exec db \
    pg_dump -U gitgrit gitgrit > gitgrit-$(date +%F).sql
```

**Database restore:**
```bash
docker compose -f docker-compose.prod.yml exec -T db \
    psql -U gitgrit gitgrit < gitgrit-YYYY-MM-DD.sql
```

**Image upgrade:**
1. On the build machine, run `./scripts/build-airgap-bundle.sh 1.1`.
2. Transfer the new `.tgz`, `tar xzf`, `docker load`.
3. Edit `.env`: `TAG=1.1`.
4. `docker compose -f docker-compose.prod.yml up -d`.
5. `docker compose -f docker-compose.prod.yml exec app python manage.py airgap_setup`.

---

## 9. Verifying you're truly air-gapped

After bringing the stack up, sanity-check that the host has no egress:

```bash
docker compose -f docker-compose.prod.yml exec app \
    curl -sS --max-time 3 https://www.google.com
```

This **must fail**. If it succeeds, the host still has internet access
and the install is not actually air-gapped.

Browser-side: open the app in a browser with DevTools → Network. Filter
for `googleapis`, `jsdelivr`, `unpkg`, `github.com` — there should be
zero requests outside `${SITE_URL}`.
