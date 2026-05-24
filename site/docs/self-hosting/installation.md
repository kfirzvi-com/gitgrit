# Installation

This page walks you end-to-end through a self-hosted GitGrit install
against your internal self-hosted GitLab. Before you start, skim the
[prerequisites](index.md#prerequisites) — most install failures come
from one of those items being missing rather than from a bug in the
steps below.

The install is split into two phases:

1. **On the build machine** (has internet): produce a self-contained
   tarball you can ship across the approval boundary.
2. **On the air-gap host**: place the CA bundle, fill in `.env`, bring
   the stack up, and sign in.

---

## Phase 1 — Get the bundle

There are two ways to obtain a bundle. **Downloading a published
release** is the recommended path — every `v*.*.*` tag pushed to the
GitGrit repository produces an artifact on the
[releases page](https://github.com/kfirzvi-com/gitgrit/releases),
built by CI from a clean, reproducible checkout. **Building from a
local checkout** is for development, custom forks, or shipping from
a non-tagged commit.

=== "Download a release (recommended)"

    On any machine with internet access:

    ```bash
    VERSION=1.0   # match the GitHub release you intend to ship
    BASE=https://github.com/kfirzvi-com/gitgrit/releases/download/v${VERSION}
    curl -fLO "${BASE}/gitgrit-install-${VERSION}.tgz"
    curl -fLO "${BASE}/gitgrit-install-${VERSION}.tgz.sha256"
    sha256sum -c "gitgrit-install-${VERSION}.tgz.sha256"
    ```

    The `sha256sum -c` step is the integrity check — it must print
    `gitgrit-install-1.0.tgz: OK`. Don't proceed if it doesn't; the
    download is corrupt or doesn't match the published artifact.

    !!! tip "Pinning to a specific release"
        Always download by an exact version tag (`v1.0`), not the
        "latest release" alias. The CI workflow that produces these
        artifacts also stamps `GIT_SHA` into the images — pinning the
        URL pins the source-of-truth too. Compliance audits will ask
        which commit shipped; this is how you answer.

=== "Build from a local checkout"

    Use this path when:

    - You're shipping from a non-tagged commit.
    - You've forked GitGrit and made changes.
    - You don't trust prebuilt artifacts and want to build from source
      yourself.

    Requires Docker 24+ on the build machine. From a checkout of the
    gitgrit repository at the commit you intend to ship:

    ```bash
    ./scripts/build-airgap-bundle.sh 1.1
    ```

    The first argument is the image tag. Use a real version (`1.1`,
    `2026.05.23`, whatever your release scheme is) — operators will see
    this on their containers and reference it in tickets.

    The script:

    - Refuses to build if the working tree is dirty so the image's
      `GIT_SHA` stamp corresponds to a reproducible commit. Set
      `ALLOW_DIRTY=1` to override; the stamp then becomes `<sha>-dirty`
      so the bundle is still traceable.
    - Builds `gitgrit-app:1.1` and `gitgrit-sandbox:1.1` with `GIT_SHA`
      and `GIT_TAG` baked in as `--build-arg`.
    - Pulls `postgres:15`.
    - `docker save`s all three images into one tarball.
    - Wraps the tarball plus compose file, `.env.example`, and these
      docs into `gitgrit-install-1.1.tgz`.

    Set `OUT_DIR=/some/path` to write the outputs somewhere other than
    the repo root.

    ### Verify before shipping

    Confirm the SHA the script claims to have stamped actually landed
    in both built images:

    ```bash
    HEAD_SHA=$(git rev-parse HEAD)
    docker image inspect gitgrit-app:1.1     --format '{{json .Config.Env}}' | grep -q "GIT_SHA=$HEAD_SHA" && echo "app:1.1 OK"
    docker image inspect gitgrit-sandbox:1.1 --format '{{json .Config.Env}}' | grep -q "GIT_SHA=$HEAD_SHA" && echo "sandbox:1.1 OK"
    ```

    The build script does this same check internally and aborts on
    failure, but verifying by hand once before shipping confirms what
    you're about to hand off.

---

However you obtained the `.tgz`, transfer it to the air-gap host by
whatever channel is approved — USB, internal SFTP, write-once media.
The bundle is self-contained; nothing else needs to cross the boundary.

---

## Phase 2 — Install on the air-gap host

Eight steps, in order. Each must succeed before the next.

### 1. Unpack and load images

```bash
tar xzf gitgrit-install-1.1.tgz
docker load -i gitgrit-bundle-1.1.tar
docker image ls | grep -E 'gitgrit|postgres'
```

You should see three images: `gitgrit-app:1.1`, `gitgrit-sandbox:1.1`,
`postgres:15`.

### 2. Place the operator CA bundle

Put a PEM file at the path you'll set in `.env` as
`GITGRIT_CUSTOM_CA_FILE_PATH` (default `/opt/gitgrit/ca-bundle.pem`).

!!! danger "This is the #1 trip-up at install"
    The PEM **must** be the issuing CA chain that signed your internal
    GitLab's TLS cert — **not** the GitLab server cert itself. If your
    network has a TLS-intercepting proxy, append that intercepting CA
    to the same file.

If you generated the CA yourself with `openssl req -x509`, the CA cert
**must** include these X.509v3 extensions or modern OpenSSL will reject
the chain with `CA cert does not include key usage extension` at TLS
handshake time:

```
basicConstraints = critical, CA:TRUE
keyUsage         = critical, digitalSignature, keyCertSign, cRLSign
```

The bundle is mounted read-only into the app container and any sandbox
containers it spawns, at `/etc/ssl/certs/custom-ca.pem`. It's consumed by:

- The app's `requests` library, via `REQUESTS_CA_BUNDLE`
- The sandbox's `urllib`, via `SSL_CERT_FILE`

Both env vars are set automatically by `docker-compose.full.yaml`.

### 3. Create the OAuth application in GitLab

In your internal GitLab admin UI:

- **Admin → Applications → New application**
- **Name**: `gitgrit` (or anything memorable to your team)
- **Redirect URI**: `${SITE_URL}/accounts/gitlab/login/callback/`
- **Scopes**: `read_user`, `read_api`, `read_repository`

!!! warning "Exact match required"
    The redirect URI must match `SITE_URL` exactly — including scheme
    (`https://`) and trailing slash. Any mismatch produces a
    `redirect_uri mismatch` error from GitLab at first sign-in.

Save the Application ID and Secret — you'll paste them into `.env` in
the next step. There's no way to retrieve the secret later, so capture
it before you close the page.

### 4. Configure `.env`

```bash
cp .env.example .env
$EDITOR .env
```

Required values:

| Variable | What to set |
|---|---|
| `SITE_URL` | Non-localhost hostname your internal GitLab can reach for webhook callbacks (e.g. `https://gitgrit.acme.internal`) |
| `SECRET_KEY` | Generate per the comment in `.env.example` |
| `GITGRIT_ENCRYPTION_KEY` | Fernet key, generate per the comment |
| `POSTGRES_PASSWORD` | Anything strong |
| `GITLAB_URL` | Your internal GitLab root URL, no trailing slash, HTTPS |
| `GITLAB_CLIENT_ID` / `GITLAB_CLIENT_SECRET` | From step 3 above |
| `GITGRIT_CUSTOM_CA_FILE_PATH` | The host path where you placed the PEM in step 2 |
| `SANDBOX_DNS` | Comma-separated internal resolver IPs (e.g. `10.0.0.53,10.0.0.54`) |

Confirm the auth toggles for an air-gap default:

```ini
AUTH_PROVIDER_GITLAB_ENABLED=True
AUTH_PROVIDER_GITHUB_ENABLED=False
AUTH_PROVIDER_GOOGLE_ENABLED=False
```

The full environment variable reference lives in
[Operations → Environment reference](operations.md#environment-variable-reference).

!!! danger "Never rotate `SECRET_KEY` or `GITGRIT_ENCRYPTION_KEY` after deploy"
    Both are used to encrypt data at rest. Rotating them invalidates
    sessions and **decrypts existing OAuth tokens incorrectly** — every
    user has to reconnect their GitLab account, and stored webhook
    secrets become unreadable. Generate once, treat them like the
    database password.

### 5. Bring up the stack

```bash
docker compose -f docker-compose.full.yaml up -d
docker compose -f docker-compose.full.yaml ps           # both containers Up
docker compose -f docker-compose.full.yaml logs app --tail=20
```

The compose file uses `pull_policy: never` on both images, so the
air-gap host doesn't reach for any registry — it uses the images you
loaded in step 1.

### 6. Run install-time checks

```bash
docker compose -f docker-compose.full.yaml exec app python manage.py airgap_setup
docker compose -f docker-compose.full.yaml exec app python manage.py airgap_smoketest --check-isolation
```

**`airgap_setup`** runs migrations, validates `SITE_URL` and
`GITGRIT_CUSTOM_CA_FILE_PATH`, syncs the Django Site row, and purges
`SocialApp` rows for disabled providers. It hard-fails if the CA path is
unset — by design, so you find out at install rather than weeks later at
first OAuth attempt. It's idempotent — re-run after every `.env` change.

**`airgap_smoketest --check-isolation`** should print four green OKs:

```
OK    GITLAB_URL=https://gitlab.acme.internal
OK    REQUESTS_CA_BUNDLE=/etc/ssl/certs/custom-ca.pem (...bytes)
OK    https://.../api/v4/version returned 401 JSON with GitLab-shaped body — looks like a real GitLab
OK    public internet appears blocked (www.google.com:443 is unreachable)
airgap_smoketest PASSED
```

Any FAIL message names the exact thing to fix (CA chain, DNS, isolation,
etc.). Don't proceed past a FAIL — the install isn't done. The
[common gotchas table](operations.md#common-gotchas) maps each FAIL
message to the step where you correct it.

!!! tip "Why TCP, not HTTPS, for the isolation probe"
    `--check-isolation` opens a raw TCP connection to
    `www.google.com:443`, not an HTTPS request. With a customer-only CA
    bundle set, an HTTPS probe would fail with `SSLError` even on a
    wide-open network — which would silently look like "isolated." The
    TCP probe sidesteps TLS entirely and only succeeds if the L4 path
    really works.

### 7. Create the first admin user

```bash
docker compose -f docker-compose.full.yaml exec app \
    python manage.py createsuperuser
```

Follow the prompts. This account can manage Django admin and bootstrap
the first workspace; day-to-day operators sign in via GitLab OAuth.

### 8. First login

Open `${SITE_URL}/accounts/login/` in a browser.

!!! warning "Browser must trust your operator CA"
    The browser's trust store must contain your operator CA — otherwise
    it'll block the redirect to your internal GitLab with a "your
    connection is not private" warning. Import the CA into the
    operator's system or browser trust store before this step.

Click **Sign in with GitLab** → consent in GitLab → land on the GitGrit
dashboard.

From there:

1. Create a workspace.
2. **Settings → Connections** → connect to your internal GitLab (uses
   `GITLAB_URL` from `.env` and the OAuth token just minted).
3. Import a project — listed via `${GITLAB_URL}/api/v4/projects`.
4. Create your first policy via the UI editor and activate it.
5. Push a commit to the project. The webhook fires, the sandbox runner
   spawns a `runsc`-isolated container, and the policy result lands in
   the database and the UI.

You're installed.

## What's next

- **[Operations](operations.md)** for backup, upgrade, troubleshooting,
  the network topology diagram, and the environment variable reference.
- **[Writing Policies](../getting-started/policies.md)** — the policy
  authoring guide. Same API as cloud.
