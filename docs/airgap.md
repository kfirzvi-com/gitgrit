# Air-gapped GitGrit deployment

GitGrit can run inside a closed network with no internet access at install
or runtime, connected to a self-hosted GitLab over the operator's own TLS
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
- **No default route to the public internet** (firewall, missing
  gateway, or VPC subnet with no NAT). `airgap_smoketest --check-isolation`
  verifies this at install time.
- An internal GitLab CE the host can reach over HTTPS, with admin access
  for creating an OAuth application
- Optional: a reverse proxy / load balancer terminating TLS in front of
  the app

---

## 2. Build the bundle

On the internet-connected build machine, from a checkout of this repo
at the commit you intend to ship:

```bash
./scripts/build-airgap-bundle.sh 1.1
```

The script refuses to build if the working tree is dirty so that the
SHA stamped into the image actually corresponds to a reproducible
commit. Set `ALLOW_DIRTY=1` to override (the stamp becomes
`<sha>-dirty` so the bundle is still traceable). Set `OUT_DIR=/some/path`
to write the outputs anywhere other than the repo root.

Produces `gitgrit-install-1.1.tgz` containing:
- `gitgrit-bundle-1.1.tar` — `docker save` of `gitgrit-app:1.1`,
  `gitgrit-sandbox:1.1`, `postgres:15`
- `docker-compose.full.yaml`
- `.env.example`
- `docs/airgap.md` (this file)

### 2a. Verify before shipping

Confirm the SHA the script claims to have stamped actually landed in
both built images:

```bash
HEAD_SHA=$(git rev-parse HEAD)
docker image inspect gitgrit-app:1.1     --format '{{json .Config.Env}}' | grep -q "GIT_SHA=$HEAD_SHA" && echo "app:1.1 OK"
docker image inspect gitgrit-sandbox:1.1 --format '{{json .Config.Env}}' | grep -q "GIT_SHA=$HEAD_SHA" && echo "sandbox:1.1 OK"
```

The build script does this same check internally and aborts if it fails,
but verifying by hand confirms what you're about to ship.

Transfer the `.tgz` to the air-gap host by whatever channel is approved
(USB, internal SFTP, etc.).

---

## 3. Install on the air-gap host

Eight steps, in order. Each must succeed before the next.

### 3a. Unpack and load images

```bash
tar xzf gitgrit-install-1.1.tgz
docker load -i gitgrit-bundle-1.1.tar      # loads gitgrit-app, gitgrit-sandbox, postgres
docker image ls | grep -E 'gitgrit|postgres'   # expect three images
```

### 3b. Place the operator CA bundle

Put a PEM file at the path you'll set in `.env` as `GITGRIT_CUSTOM_CA_FILE_PATH`
(default `/opt/gitgrit/ca-bundle.pem`).

**The PEM must be the issuing CA chain that signed your internal GitLab's
TLS cert — not the GitLab server cert itself.** If your network has a
TLS-intercepting proxy, append that intercepting CA to the same file.
This trips ops teams more often than anything else; double-check.

If you generated the CA yourself with `openssl req -x509`, the CA cert
**must** include these X.509v3 extensions or modern OpenSSL will reject
the chain with `CA cert does not include key usage extension` at TLS
handshake time (you'll see this in `airgap_smoketest` output below):

```
basicConstraints = critical, CA:TRUE
keyUsage         = critical, digitalSignature, keyCertSign, cRLSign
```

The bundle is mounted read-only into the app container and any sandbox
containers it spawns. Used by:
- The app's `requests` library (via `REQUESTS_CA_BUNDLE`).
- The sandbox's `urllib` (via `SSL_CERT_FILE`).

### 3c. Create the OAuth application in GitLab

In your internal GitLab admin UI:
- **Admin → Applications → New application**
- Name: `gitgrit` (or anything)
- Redirect URI: `${SITE_URL}/accounts/gitlab/login/callback/` — must
  exactly match `SITE_URL` (including scheme and trailing slash) or
  GitLab will reject the callback with `redirect_uri mismatch`
- Scopes: `read_user`, `read_api`, `read_repository`

Save the Application ID and Secret — you'll paste them into `.env` in
the next step.

### 3d. Configure `.env`

```bash
cp .env.example .env
$EDITOR .env
```

Required (see §5 for the full reference):
- `SITE_URL` — non-localhost hostname your internal GitLab can reach
- `SECRET_KEY`, `GITGRIT_ENCRYPTION_KEY` — generate per the file's comments
- `POSTGRES_PASSWORD` — anything strong
- `GITLAB_URL` — your internal GitLab root URL, no trailing slash, must
  be HTTPS
- `GITLAB_CLIENT_ID` / `GITLAB_CLIENT_SECRET` — from §3c above
- `GITGRIT_CUSTOM_CA_FILE_PATH` — must match where you put the PEM in §3b
- `SANDBOX_DNS` — comma-separated internal resolver IPs (not `127.0.0.11`)

Confirm:
```
AUTH_PROVIDER_GITLAB_ENABLED=True
AUTH_PROVIDER_GITHUB_ENABLED=False
AUTH_PROVIDER_GOOGLE_ENABLED=False
```

### 3e. Bring up the stack

```bash
docker compose -f docker-compose.full.yaml up -d
docker compose -f docker-compose.full.yaml ps           # both containers Up
docker compose -f docker-compose.full.yaml logs app --tail=20
```

### 3f. Run install-time checks

```bash
docker compose -f docker-compose.full.yaml exec app python manage.py airgap_setup
docker compose -f docker-compose.full.yaml exec app python manage.py airgap_smoketest --check-isolation
```

`airgap_setup` runs migrations, validates `SITE_URL` and `GITGRIT_CUSTOM_CA_FILE_PATH`,
syncs the Django Site row, and purges `SocialApp` rows for disabled
providers. Hard-fails if `GITGRIT_CUSTOM_CA_FILE_PATH` is unset — by design, so the
operator finds out at install rather than weeks later at first OAuth
attempt. Idempotent — re-run after every `.env` change.

`airgap_smoketest --check-isolation` should print four green OKs:

```
OK    GITLAB_URL=https://gitlab.acme.internal
OK    REQUESTS_CA_BUNDLE=/etc/ssl/certs/custom-ca.pem (...bytes)
OK    https://.../api/v4/version returned 401 JSON with GitLab-shaped body — looks like a real GitLab
OK    public internet appears blocked (www.google.com:443 is unreachable)
airgap_smoketest PASSED
```

Any FAIL message names the exact thing to fix (CA chain, DNS, isolation,
etc.). Don't proceed past a FAIL.

### 3g. Create the first admin user

```bash
docker compose -f docker-compose.full.yaml exec app \
    python manage.py createsuperuser
```

### 3h. First login

Open `${SITE_URL}/accounts/login/` in a browser. **The browser's trust
store must contain your operator CA** — otherwise the browser will block
the redirect to your internal GitLab with a "your connection is not
private" warning. Import the CA into the operator's system or browser
trust store first.

Click **Sign in with GitLab** → consent in GitLab → land on the GitGrit
dashboard. Then:

- Create a workspace.
- **Settings → Connections** → connect to your internal GitLab (uses
  `GITLAB_URL` from `.env` and the OAuth token just minted).
- Import a project. Listed via `${GITLAB_URL}/api/v4/projects`.
- Create your first policy via the UI editor and activate it.
- Push a commit to the project. The webhook fires, the sandbox runner
  spawns a `runsc`-isolated container, and the policy result lands in
  the DB and the UI.

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
| `SITE_URL` | Public hostname the operator's GitLab can reach for webhooks. Must not be `localhost`. |
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
| `GITGRIT_CUSTOM_CA_FILE_PATH` | Host path to the operator CA bundle PEM. |

`AIRGAPPED`, `SANDBOX_NETWORK`, `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`,
`DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` are set automatically by
`docker-compose.full.yaml` — operators should not override them.

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
> (`docker compose -f docker-compose.full.yaml down`) before bringing
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
docker compose -f docker-compose.full.yaml logs -f app
```

**Database backup:**
```bash
docker compose -f docker-compose.full.yaml exec db \
    pg_dump -U gitgrit gitgrit > gitgrit-$(date +%F).sql
```

**Database restore:**
```bash
docker compose -f docker-compose.full.yaml exec -T db \
    psql -U gitgrit gitgrit < gitgrit-YYYY-MM-DD.sql
```

**Image upgrade:**
1. On the build machine, run `./scripts/build-airgap-bundle.sh 1.1`.
2. Transfer the new `.tgz`, `tar xzf`, `docker load`.
3. Edit `.env`: `TAG=1.1`.
4. `docker compose -f docker-compose.full.yaml up -d`.
5. `docker compose -f docker-compose.full.yaml exec app python manage.py airgap_setup`.

---

## 9. Verifying you're truly air-gapped

`airgap_smoketest --check-isolation` (run in §3f) is the primary check —
it probes `www.google.com:443` at TCP level (not HTTPS, so a
customer-only CA bundle can't falsely make a wide-open network look
blocked) and fails loudly if the connection succeeds.

Belt-and-braces — if you want to double-check by hand:

```bash
docker compose -f docker-compose.full.yaml exec app \
    curl -sS --max-time 3 https://www.google.com
```

This **must fail**. If it succeeds, the host still has internet access
and the install is not actually air-gapped.

Browser-side: open the app in a browser with DevTools → Network. Filter
for `googleapis`, `jsdelivr`, `unpkg`, `github.com` — there should be
zero requests outside `${SITE_URL}`.

---

## 10. Common gotchas

In order of how often we see them at install:

| Symptom | Cause | Where to fix |
|---|---|---|
| `airgap_smoketest`: `TLS handshake to https://… failed: … CERTIFICATE_VERIFY_FAILED` | Wrong PEM at `GITGRIT_CUSTOM_CA_FILE_PATH` — either pointing at the GitLab *server cert* instead of the issuing CA chain, or a self-generated CA missing `basicConstraints` / `keyUsage` X.509v3 extensions | §3b |
| `airgap_smoketest`: `could not connect to https://…: …Name or service not known` | Container can't resolve `GITLAB_URL` host | Internal DNS or `/etc/hosts` on the air-gap host |
| `airgap_smoketest`: returned 200 (not 401) | Probe hitting a non-GitLab service at `GITLAB_URL` (reverse proxy, captive portal) | Fix `GITLAB_URL` |
| `airgap_setup`: `GITGRIT_CUSTOM_CA_FILE_PATH is not set` | Variable empty or commented out in `.env` | §3d |
| OAuth callback: `redirect_uri mismatch` | GitLab application's redirect URI doesn't exactly match `${SITE_URL}/accounts/gitlab/login/callback/` | §3c — edit the GitLab application |
| App startup: `password authentication failed for user "gitgrit"` against an unexpected IP | A second airgap stack on the same host shares the fixed-name `gitgrit_internal` bridge — `db` resolves to both containers; the app picks the wrong one | §6 — tear down the older stack first |
| Sandbox runs work but `docker inspect <id> .HostConfig.Runtime` shows `runc` (not `runsc`) | gVisor not registered with Docker | §4 — `sudo runsc install && sudo systemctl restart docker` |
| Browser: "your connection is not private" at the redirect to GitLab | OS / browser trust store doesn't have your operator CA | §3h — import the CA |
| TLS errors with "cert not yet valid" / "cert expired" | Host clock drifted | §7 — point at internal NTP |
