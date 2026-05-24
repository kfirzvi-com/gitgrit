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

Policy code runs inside containers wrapped by gVisor to keep them
isolated from the host. Install `runsc` system-wide on the air-gap host
before bringing the stack up:

- gVisor's offline-install instructions: [gvisor.dev/docs/user_guide/install/](https://gvisor.dev/docs/user_guide/install/).
  Download the binary on the build machine, ship it alongside the
  bundle.
- After install, restart the Docker daemon. Verify with
  `docker info | grep runsc` — you should see `runsc` listed under the
  available runtimes.

If `runsc` is missing, the sandbox runner logs a warning and falls back
to the default Docker runtime. Policies still run, but isolation is
weaker. **Treat a missing `runsc` as an install blocker** if your
security posture relies on the sandbox boundary.

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
| `SANDBOX_DNS` | Comma-separated internal DNS resolvers. gVisor cannot use Docker's embedded DNS. |
| `GITGRIT_CUSTOM_CA_FILE_PATH` | Host path to the operator CA bundle PEM. |

Compose-internal (do **not** override in `.env` — set automatically by
`docker-compose.full.yaml`):

`AIRGAPPED`, `SANDBOX_NETWORK`, `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`,
`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`.
