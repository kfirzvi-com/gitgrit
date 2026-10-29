---
title: "Operating Self-Hosted GitGrit"
---

# Operations

Reference and ongoing-ops material for a running self-hosted GitGrit
instance. If you're partway through an install and hit a failure,
jump straight to the [Common gotchas](#common-gotchas) table — every
install-time `FAIL` message is mapped to its fix below.

## Common gotchas

Ordered by how often we see them at install:

| Symptom | Cause | Fix |
|---|---|---|
| `airgap_smoketest`: `TLS handshake to https://… failed: … CERTIFICATE_VERIFY_FAILED` | Wrong PEM at `GITGRIT_CUSTOM_CA_FILE_PATH` — either pointing at the GitLab *server cert* instead of the issuing CA chain, or a self-generated CA missing `basicConstraints` / `keyUsage` X.509v3 extensions | [Installation → Place the operator CA bundle](installation.md#2-place-the-operator-ca-bundle) |
| `airgap_smoketest`: `could not connect to https://…: …Name or service not known` | Container can't resolve `GITLAB_URL` host | Fix internal DNS, or add an `/etc/hosts` entry on the air-gap host |
| `airgap_smoketest`: returned 200 (not 401) | The probe is hitting a non-GitLab service at `GITLAB_URL` (reverse proxy, captive portal, wrong service on that hostname) | Fix `GITLAB_URL` in `.env` |
| `airgap_setup`: `GITGRIT_CUSTOM_CA_FILE_PATH is not set` | Variable empty or commented out in `.env` | [Installation → Configure .env](installation.md#4-configure-env) |
| OAuth callback: `redirect_uri mismatch` | GitLab application's redirect URI doesn't exactly match `${SITE_URL}/accounts/gitlab/login/callback/` | [Installation → Create the OAuth application](installation.md#3-create-the-oauth-application-in-gitlab) — edit the GitLab application, save |
| App startup: `password authentication failed for user "gitgrit"` against an unexpected IP | A second GitGrit stack on the same host is sharing the fixed-name `gitgrit_internal` bridge — `db` resolves to both containers; the app picks the wrong one | [Network topology](#network-topology) — tear down the older stack with `docker compose -f docker-compose.full.yaml down` |
| Sandbox runs work but `docker inspect <id> .HostConfig.Runtime` shows `runc` (not `runsc`) | gVisor not registered with Docker | [gVisor](#gvisor-runsc) — `sudo runsc install && sudo systemctl restart docker` |
| Browser: "your connection is not private" at the redirect to GitLab | OS / browser trust store doesn't have your operator CA | Import the CA into the operator's system or browser trust store |
| TLS errors with "cert not yet valid" / "cert expired" anywhere | Host clock has drifted | [Time / NTP](#time-ntp) — point at internal NTP |

## Network topology

```
            ┌─ gitgrit_internal (bridge) ─────────────────────────────┐
            │                                                          │
            │   ┌─────────┐    ┌────────────────────┐    ┌──────────┐ │
            │   │  app    │    │  on-demand sandbox │    │ internal │ │
            │   │ (Django)│◀──▶│  (gVisor / runsc)  │◀──▶│  GitLab  │ │
            │   └────┬────┘    └────────────────────┘    └──────────┘ │
            │        │                                                 │
            │   ┌────▼────┐                                            │
            │   │   db    │                                            │
            │   │(postgres)                                            │
            │   └─────────┘                                            │
            └──────────────────────────────────────────────────────────┘
```

`SANDBOX_NETWORK=gitgrit_internal` in compose ties spawned sandbox
containers to the same bridge as the app and db, so they can resolve
and reach your internal GitLab on the same network.

!!! warning "One stack per host"
    The `gitgrit_internal` bridge has a **fixed name** (the sandbox
    runner needs to attach on-demand containers to a known network from
    outside compose). If you bring up a second GitGrit stack on the same
    host, both stacks share the bridge — Docker DNS for `db` resolves to
    *both* containers and the app silently picks whichever IP comes back
    first.

    Symptom: the app logs `password authentication failed for user
    "gitgrit"` against an IP that doesn't match the stack it was
    supposed to talk to. If you need multiple installs on one host,
    `docker compose -f docker-compose.full.yaml down` the older stack
    first.

## gVisor (`runsc`)

Standard code runs inside containers wrapped by gVisor to keep them
isolated from the host. Install `runsc` system-wide on the air-gap host
before bringing the stack up:

- gVisor's offline-install instructions: [gvisor.dev/docs/user_guide/install/](https://gvisor.dev/docs/user_guide/install/).
  Download the binary on the build machine, ship it alongside the
  bundle.
- After install, restart the Docker daemon. Verify with
  `docker info | grep runsc` — you should see `runsc` listed under the
  available runtimes.

If `runsc` is missing, the sandbox runner logs a warning and falls back
to the default Docker runtime. Standards still run, but isolation is
weaker. **Treat a missing `runsc` as an install blocker** if your
security posture relies on the sandbox boundary.

## Background worker (Procrastinate)

Standard runs never happen inside a web request. When you press
**Run** / **Run All** on a project, attach, save or activate a standard,
or a webhook delivery arrives, GitGrit records the executions as
*running* and hands them to the Procrastinate worker, which starts the
sandboxed containers and writes the results back — the project page
refreshes itself as they land. The worker is therefore **required for
standard runs**, not only for the dependency graph it was originally
added for.

`docker-compose.full.yaml` runs it as the `worker` service, from the
same image and environment as `app`, with the same Docker socket and
sandbox mounts (it starts the sandbox). Outside compose, run:

```bash
python manage.py procrastinate worker --queues=graph,standards --concurrency 4
```

If nothing is consuming the `standards` queue, standards show as
*running* on the project page and no results appear. Check the worker
first — the compose service has a health check, so `ps` shows it as
`unhealthy` when it cannot reach the database or the schema is behind:

```bash
docker compose -f docker-compose.full.yaml ps worker
docker compose -f docker-compose.full.yaml logs worker --tail=50
```

Runs the worker never finishes do not stay *running* forever. A run
still in that state after `STANDARD_RUN_STALE_MINUTES` (default 60) is
marked as an error by a periodic job, with a message pointing at the
worker, and the standard can be run again. Raise the value if your LLM
standards legitimately take longer end to end.

## Time / NTP

Air-gap hosts with drifted clocks break TLS verification in non-obvious
ways — `cert not yet valid`, `cert expired`, `signature verify failed`.
Point the host at your internal NTP server before bringing the stack
up, and monitor clock drift the same way you'd monitor any other
production host.

## Common operations

### Tail logs

```bash
docker compose -f docker-compose.full.yaml logs -f app
```

Add `db` or `gitgrit-sandbox-*` (container names rotate per run) for
service-specific tails.

### Database backup

```bash
docker compose -f docker-compose.full.yaml exec db \
    pg_dump -U gitgrit gitgrit > gitgrit-$(date +%F).sql
```

This is a logical dump and includes everything — Django app state,
encrypted OAuth tokens, audit history. Store backups with at least the
same access controls as the host itself.

### Database restore

```bash
docker compose -f docker-compose.full.yaml exec -T db \
    psql -U gitgrit gitgrit < gitgrit-YYYY-MM-DD.sql
```

!!! warning "Encryption key must match"
    A restore is only useful if the destination `GITGRIT_ENCRYPTION_KEY`
    matches the source. Restoring a backup onto a host with a different
    encryption key leaves stored OAuth tokens unreadable. Treat the
    key as part of the backup metadata — store it (separately, in a
    secrets manager) alongside the dump.

### Image upgrade

1. On the build machine, run `./scripts/build-airgap-bundle.sh 1.2`
   from the new commit you intend to ship.
2. Transfer the new `.tgz` to the air-gap host. `tar xzf` it, `docker
   load -i gitgrit-bundle-1.2.tar`.
3. Edit `.env`: bump `TAG=1.2`.
4. `docker compose -f docker-compose.full.yaml up -d` — Docker swaps
   the containers in place using the loaded `1.2` images.
5. `docker compose -f docker-compose.full.yaml exec app python manage.py airgap_setup`
   — applies any new migrations and re-syncs SocialApp rows.

Backwards-incompatible changes are called out in the release notes
shipped inside the bundle. Read them before each upgrade.

## Verifying you're truly air-gapped

`airgap_smoketest --check-isolation` (run during install) is the
primary check — it probes `www.google.com:443` at TCP level (not HTTPS,
so a customer-only CA bundle can't falsely make a wide-open network
look blocked) and fails loudly if the connection succeeds.

Belt-and-braces — double-check by hand:

```bash
docker compose -f docker-compose.full.yaml exec app \
    curl -sS --max-time 3 https://www.google.com
```

This **must fail**. If it succeeds, the host still has internet access
and the install is not actually air-gapped.

Browser-side: open the app in a browser with DevTools → Network. Filter
for `googleapis`, `jsdelivr`, `unpkg`, `github.com`, `fonts.gstatic.com`
— there should be zero requests outside `${SITE_URL}`. The vendored
fonts under `app/static/app/vendor/fonts/` are why; the `{% if
airgapped %}` template branch in `base.html` is what gates the swap.

## Managing access

Superusers run the instance from **Admin** in the avatar menu
(`${SITE_URL}/staff/`).

### Who can get in

`GITGRIT_SIGNUP_MODE` decides what happens the first time someone signs in,
with GitLab (or Google/GitHub, if enabled) or with an email and password:

| Mode | First sign-in | Superusers emailed | Gets in |
|---|---|---|---|
| `approval` (default) | An access request; "waiting for approval" | Right away | When a superuser approves |
| `onboarding` | A short form (name, company, role, goals), then waiting | Once the form is in | When a superuser approves |
| `open` | Signed in | Never | Immediately, but in no workspace until someone adds them |

Approving always puts the person in a workspace, an existing one or a new
one named after their company, with a role. Rejecting keeps them out.

Someone who signs up with an email and password first gets a link to
confirm the address. Their request reaches superusers (and the queue) only
once they've followed it. Sign-ins through GitLab, Google or GitHub carry the
provider's word for the address and skip this. Forgotten passwords are reset
from **Forgot password?** on the sign-in page; both need
[outgoing email](#environment-variable-reference) set up.

### Superusers

**Admin → Superusers** lists who they are and who made each one a
superuser. A superuser can make another active account a superuser, remove
one, or step down. There is always at least one: the last superuser can't
be removed, deactivated or deleted, here or in the Django admin.

Superusers can open any workspace from the workspace switcher. That is the
**support view**: full access, a banner while it's on, and every change
logged.

### Workspaces

Only superusers create workspaces (**+ New Workspace** in the workspace
switcher, or while approving someone). Every workspace has at least one
owner; roles and members are managed in the workspace's own settings, see
[Workspaces & Members](../getting-started/workspaces.md).

## Environment variable reference

Operator-fillable (you set these in `.env`):

| Variable | Purpose |
|---|---|
| `TAG` | Image tag, matches the bundle version. |
| `SITE_URL` | Public hostname your internal GitLab can reach for webhooks. Must not be `localhost`. |
| `APP_PORT` | Host port to expose the app on. Default `3000`. |
| `SECRET_KEY` | Django signing key. **Never rotate** after deploy — invalidates sessions and stored OAuth tokens. |
| `GITGRIT_ENCRYPTION_KEY` | Fernet key for OAuth-token-at-rest encryption. **Never rotate** for the same reason. |
| `POSTGRES_USER` / `POSTGRES_DB` / `POSTGRES_PASSWORD` | Database credentials. |
| `AUTH_PROVIDER_GITHUB_ENABLED` | `True` / `False` (exact strings). Air-gap default `False`. |
| `AUTH_PROVIDER_GITLAB_ENABLED` | `True` / `False`. Air-gap default `True`. |
| `AUTH_PROVIDER_GOOGLE_ENABLED` | `True` / `False`. Air-gap default `False`. |
| `GITLAB_URL` | Root URL of your internal GitLab, no trailing slash. |
| `GITLAB_CLIENT_ID` / `GITLAB_CLIENT_SECRET` | OAuth app credentials from GitLab. Callback: `${SITE_URL}/accounts/gitlab/login/callback/`. |
| `GITGRIT_SIGNUP_MODE` | `approval` (default), `onboarding` or `open`. See [Managing access](#who-can-get-in). |
| `GITGRIT_SETUP_TOKEN` | Token for the first-run `/setup/` page. Empty (default) derives one from `SECRET_KEY`; `manage.py setup_token` prints it. |
| `EMAIL_HOST` / `EMAIL_PORT` / `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` / `EMAIL_USE_TLS` | SMTP relay for access-request and approval emails. Port defaults to `587` with STARTTLS. Without `EMAIL_HOST`, emails only go to the app log. |
| `DEFAULT_FROM_EMAIL` | Sender address, e.g. `GitGrit <gitgrit@acme.internal>`. |
| `GITGRIT_EMAIL_BACKEND` | `smtp` (default when `EMAIL_HOST` is set), `console` (default otherwise: emails go to the log), or `ses`: the Amazon SES API with the host's AWS credentials, for installs running on AWS. `AWS_SES_REGION` picks the region. |
| `GITGRIT_UPLOADS_BUCKET` / `GITGRIT_UPLOADS_REGION` | Keep [artifact projects](../getting-started/artifact-projects.md)' uploaded archives in this private S3 bucket, with the host's AWS credentials, for installs running on AWS. Region defaults to `eu-north-1`. Unset (the air-gap default): a local directory, see `GITGRIT_UPLOADS_ROOT`. |
| `SANDBOX_DNS` | Comma-separated internal DNS resolvers. gVisor cannot use Docker's embedded DNS. |
| `GITGRIT_CUSTOM_CA_FILE_PATH` | Host path to the operator CA bundle PEM. |

Compose-internal (do **not** override in `.env` — set automatically by
`docker-compose.full.yaml`):

`AIRGAPPED`, `SANDBOX_NETWORK`, `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`,
`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, and
`GITGRIT_UPLOADS_ROOT` (`/var/lib/gitgrit/uploads`, on the `gitgrit_uploads`
volume both `app` and `worker` mount: uploaded archives are stored by one and
read by the other, so back the volume up with the database).
