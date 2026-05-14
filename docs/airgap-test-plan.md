# GitGrit Air-gap Functional Test Plan

This document is a runbook for a developer who needs to prove that a freshly
built GitGrit air-gap bundle is fully self-sufficient: it installs on a host
with **no internet access**, lets a user sign in against a **self-hosted
GitLab**, and runs policies in a **locally spawned gVisor sandbox** — with
zero outbound calls to the public internet at any stage.

It complements `docs/airgap.md` (the operator install guide) by spelling out
what to *verify* at each step and how to provoke each failure mode.

---

## 0. Test goals

By the end of this plan, you should have evidence for all of the following:

1. The bundle can be built on an internet-connected machine and shipped as a
   single tarball.
2. The air-gap host has no public-internet egress, and GitGrit still comes
   up cleanly.
3. A user can sign in via the **self-hosted GitLab** OAuth flow over the
   customer TLS chain — and the GitLab provider button is the **only** one
   shown.
4. With no internet, the user can: create a workspace, connect a project
   from the local GitLab, create a policy, and view results.
5. A policy executes end-to-end in an on-demand **gVisor (`runsc`) sandbox
   container** spawned on the host. The sandbox reaches the local GitLab
   over the same customer CA.
6. The browser fetches **zero** assets from external CDNs — fonts, CSS, JS
   all load from the app itself.
7. The negative paths fail loudly (missing CA, drifted clock, missing DNS,
   `SITE_URL=localhost`, etc.).

---

## 1. Lab setup — hosts and network

You need three hosts (VMs are fine):

| Host | Internet? | Role |
|---|---|---|
| **build** | Yes | Runs `scripts/build-airgap-bundle.sh` once. Has Docker 24+. |
| **airgap** | **No** | Runs the GitGrit stack. Docker 24+, Compose v2, gVisor `runsc` pre-installed, internal DNS resolver reachable. |
| **gitlab** | No (internal only) | Runs a self-hosted GitLab CE (Omnibus or Docker) on a hostname like `gitlab.acme.internal`, with a TLS cert signed by your test CA. |

The `airgap` and `gitlab` hosts must be on the same internal network and
able to resolve each other by hostname. The `airgap` host must **not** have
a default route to the public internet.

### 1a. Enforce isolation on the `airgap` host

Pick one and document which you used:

- **Firewall**: drop all OUTPUT not destined for the internal subnet, e.g.
  `iptables -A OUTPUT ! -d 10.0.0.0/8 -j REJECT` (adjust to your CIDR).
- **No default gateway**: `ip route del default` and reboot to confirm
  persistence with your network config.
- **Network namespace / VLAN** with no upstream egress.

The smoketest in step 4 will confirm this empirically — do not skip it.

### 1b. CA bundle

On the build machine, generate a test CA, sign your `gitlab.acme.internal`
cert with it, and copy the **CA chain PEM** (issuing CA, not the GitLab
server cert) to `/opt/gitgrit/ca-bundle.pem` on the `airgap` host. If your
test network has a TLS-intercepting proxy, append its CA to the same file.

---

## 2. Phase A — Build the bundle (on `build`)

```bash
cd <gitgrit checkout>
./scripts/build-airgap-bundle.sh 1.0
```

### Pass criteria

- Exit code 0.
- `gitgrit-install-1.0.tgz` exists in the working directory.
- `tar tzf gitgrit-install-1.0.tgz` lists at minimum:
  - `gitgrit-bundle-1.0.tar`
  - `docker-compose.prod.yml`
  - `.env.example`
  - `docs/airgap.md`
- `docker image ls` on `build` shows `gitgrit-app:1.0`, `gitgrit-sandbox:1.0`,
  and `postgres:15` (the three images that were `docker save`d).
- The bundle tarball is under ~3 GB.

### Fail signals

- Script aborts because Docker isn't available, or because the build fails
  for a reason unrelated to the bundling (e.g., a `pip install` step
  needs the public PyPI — that would be a real bug; flag it).

---

## 3. Phase B — Transfer + install (on `airgap`)

Transfer `gitgrit-install-1.0.tgz` to the `airgap` host (USB, internal
SFTP — match what a real customer would do). On the `airgap` host:

```bash
mkdir -p /opt/gitgrit && cd /opt/gitgrit
tar xzf /path/to/gitgrit-install-1.0.tgz
docker load -i gitgrit-bundle-1.0.tar
docker image ls | grep -E 'gitgrit-(app|sandbox)|postgres'
```

### Pass criteria

- `docker load` reports loading three images.
- All three images appear in `docker image ls`.
- No image was pulled from a remote registry (verify with
  `docker events --since 1m` running in another shell during `docker load`
  — there should be `image load` events and **no** `image pull` events).

Now create `.env`:

```bash
cp .env.example .env
$EDITOR .env
```

Fill in:
- `SITE_URL` — the airgap host's hostname (e.g. `https://gitgrit.acme.internal`).
  Must be resolvable from the GitLab host.
- `SECRET_KEY` and `GITGRIT_ENCRYPTION_KEY` — generate with the commands in
  the file's comments.
- `POSTGRES_PASSWORD` — anything strong.
- `GITLAB_URL=https://gitlab.acme.internal` (no trailing slash).
- `GITLAB_CLIENT_ID` / `_SECRET` — see Phase D below; you'll create the
  OAuth app in GitLab first, then come back and fill these in.
- `SANDBOX_DNS` — your internal resolver IP(s).
- `CUSTOMER_CA_PATH=/opt/gitgrit/ca-bundle.pem` (must match where you put
  the PEM in step 1b).

Leave `AUTH_PROVIDER_GITHUB_ENABLED` and `AUTH_PROVIDER_GOOGLE_ENABLED` as
`False`. Leave `AUTH_PROVIDER_GITLAB_ENABLED=True`.

Bring the stack up:

```bash
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps
```

### Pass criteria

- `app` and `db` containers both `Up` / healthy.
- `docker compose ... logs app` shows Django starting, no `OperationalError`
  or `SSLError` traces.

---

## 4. Phase C — Verify air-gap + smoketest

### 4a. Run `airgap_setup`

```bash
docker compose -f docker-compose.prod.yml exec app \
    python manage.py airgap_setup
```

**Pass**: exit 0, output reports migrations applied (or already current),
SITE_URL validated, CA bundle readable, `Site` row synced, disabled
SocialApps purged.

**Negative test (do this once)**: temporarily set `SITE_URL=http://localhost`
in `.env`, re-run the command, expect non-zero exit and a clear error. Then
revert.

### 4b. Run `airgap_smoketest --check-isolation`

```bash
docker compose -f docker-compose.prod.yml exec app \
    python manage.py airgap_smoketest --check-isolation
```

This is the single most important test in the plan. It must:

- Confirm `GITLAB_URL` is HTTPS and reachable.
- Confirm `REQUESTS_CA_BUNDLE` points to a readable PEM.
- TLS-handshake against `${GITLAB_URL}/api/v4/version` and receive an HTTP
  JSON response (a `401` is expected and **good** — it proves you reached
  the GitLab API, not an HTML error page from a captive proxy). The probe
  endpoint must be one that GitLab always requires auth for; `/api/v4/projects`
  returns `200 []` on a default GitLab CE install when no public projects
  exist, which would false-fail the check.
- With `--check-isolation`, additionally probe `https://www.google.com` and
  **fail loudly** if it's reachable.

**Pass**: exit 0 and all checks ✓.
**Fail signals**:
- `google.com is reachable from inside the app container — this host is NOT air-gapped`. Go back to step 1a.
- TLS verification error against the GitLab API → your CA bundle is wrong
  (most common cause: you mounted the GitLab *server* cert, not the issuing
  CA chain).
- HTML response instead of JSON → there is a TLS-intercepting proxy on the
  path; you need to append its CA to the same bundle.

### 4c. Manual egress check (belt and braces)

```bash
docker compose -f docker-compose.prod.yml exec app \
    curl -sS --max-time 3 https://www.google.com
```

**Pass**: command fails (connection timeout or refused). If you get HTML
back, stop the test plan and fix the network setup.

---

## 5. Phase D — Self-hosted GitLab OAuth

### 5a. Create the OAuth app in GitLab

In the local GitLab UI: Admin Area → Applications → New application.
- Name: `gitgrit-local-test`
- Redirect URI: `${SITE_URL}/accounts/gitlab/login/callback/`
- Scopes: `read_user`, `read_api`, `read_repository` (match what GitGrit
  requests in code — if the OAuth fails after consent, check
  `app/infrastructure/platforms/gitlab/` for the exact scope list).

Paste `Application ID` and `Secret` into `.env` as `GITLAB_CLIENT_ID` /
`GITLAB_CLIENT_SECRET`. Re-run `airgap_setup` so the SocialApp row updates.

### 5b. Verify the login page shows GitLab only

Open `${SITE_URL}/accounts/login/` in a browser. **Pass**:
- A "Sign in with GitLab" button is visible.
- No GitHub or Google buttons.

This is the assertion baked into
`tests/presentation/test_login_provider_buttons.py` — run it now too:

```bash
docker compose -f docker-compose.prod.yml exec app \
    python -m pytest tests/presentation/test_login_provider_buttons.py -v
```

### 5c. Complete the OAuth flow

Click "Sign in with GitLab", consent, get bounced back to GitGrit. **Pass**:
you land on the post-login page as the GitLab user.

**Fail signals**:
- Browser shows "your connection is not private" → CA bundle on the host's
  browser/system trust store is the issue (separate from the container's
  CA bundle).
- App logs show `SSLError` during the token exchange → the *app container*
  doesn't trust your CA. Verify `REQUESTS_CA_BUNDLE` env on the running
  container: `docker compose ... exec app env | grep CA`.

---

## 6. Phase E — App functionality with no internet

Sanity-check that the normal user journey works without ever needing
internet.

| # | Action | Pass criteria |
|---|---|---|
| 1 | Create a workspace from the UI. | Workspace appears in the sidebar. |
| 2 | Connect to your local GitLab (Settings → Connections). | Connection saves; `PlatformConnection` row exists; access_token is Fernet-encrypted at rest (`docker compose exec db psql -U gitgrit -c "select substring(access_token, 1, 20) from app_platformconnection;"` — the prefix should look like `gAAAA…`). |
| 3 | Import a project from the local GitLab. | The project list is fetched from `${GITLAB_URL}/api/v4/projects`; project appears in the workspace. Tail `docker compose ... logs app` while doing this — you should see HTTPS calls to your GitLab hostname only, no `gitlab.com`. |
| 4 | Create a stack and attach the project. | Persists across page reload. |
| 5 | Create a draft policy with the built-in editor. | Saves; appears in the policy list. |
| 6 | Activate the policy. | Status flips to active. |

While you are doing this, run `tcpdump` or a packet capture on the
airgap host filtering for `dst port 443 and not net 10.0.0.0/8`
(adjust to your internal CIDR). **Pass**: zero packets captured.

---

## 7. Phase F — End-to-end policy execution in a local sandbox

This is the headline test: a policy runs in a gVisor-isolated container
spawned on the airgap host, talks to the local GitLab, and returns a
result — all without any internet.

### 7a. Preflight — verify gVisor is wired into Docker

```bash
docker info | grep -i runtime
```

**Pass**: `runsc` appears in the runtimes list.
**If missing**: install gVisor per `docs/airgap.md` §4 before continuing.
Without `runsc`, the runner falls back to the default runtime — the test
will still pass functionally, but isolation is weaker. Log this as a finding.

### 7b. Trigger a policy run

Two options — pick whichever your test plan uses:

**Option 1 — Real webhook from the local GitLab.** Push a commit to the
imported project. The webhook hits `${SITE_URL}/webhooks/gitlab/...`,
`PolicyEngine` matches active policies and spawns a sandbox.

**Option 2 — Manual trigger.** Use the "Run policy" button in the UI (or
the management command, if your branch has one).

### 7c. Observe the sandbox container

In another shell on the airgap host, **before** triggering the run:

```bash
watch -n 0.5 'docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Networks}}"'
```

When you trigger the run, you should see a short-lived container appear:

- **Image**: `gitgrit-sandbox:1.0` (must match `TAG` in `.env`).
- **Network**: `gitgrit_internal` (the `SANDBOX_NETWORK` from compose).
- **Lifetime**: seconds — it starts, runs the policy, exits.

Verify the runtime used:

```bash
# while a sandbox is running, capture its ID quickly, then:
docker inspect <id> --format '{{.HostConfig.Runtime}}'
```

**Pass**: prints `runsc`. (If it prints `runc` or empty, your gVisor install
is broken — see 7a.)

Verify the CA bundle and DNS are mounted/wired:

```bash
docker inspect <id> --format '{{json .Mounts}}' | python -m json.tool
docker inspect <id> --format '{{.HostConfig.Dns}}'
```

**Pass**:
- Mounts include `/opt/gitgrit/ca-bundle.pem` → `/etc/ssl/certs/customer-ca.pem` (read-only).
- DNS list matches `SANDBOX_DNS` from `.env`.
- The container has `SSL_CERT_FILE=/etc/ssl/certs/customer-ca.pem` in its
  environment (use `docker inspect ... .Config.Env`).

### 7d. Confirm the result lands in the DB

After the run completes, check the policy execution result in the UI (or
query the DB):

```bash
docker compose -f docker-compose.prod.yml exec db \
    psql -U gitgrit -c "select id, policy_id, passed, score, substring(message, 1, 80) from app_policyexecution order by created_at desc limit 3;"
```

**Pass**: a recent row, with `passed` set, `score` populated, and `message`
matching what your test policy was written to return. No `internal error`
or stack trace in the message column.

### 7e. Negative test — pull the network plug

While a sandbox is running, run:

```bash
docker network disconnect gitgrit_internal $(docker ps -q --filter "ancestor=gitgrit-sandbox:1.0")
```
(only viable if the run is long enough — otherwise skip).

Or, more reliably, write a test policy that makes an outbound call to
`https://www.google.com` and assert it **fails** with a connection error
(not an SSL error — the policy shouldn't be able to resolve the host at
all from the internal DNS).

---

## 8. Phase G — Browser asset audit

Open the app in a browser with DevTools → Network. Reload `${SITE_URL}/`
with cache disabled. **Pass**:

- All requests target `${SITE_URL}` — zero requests to `cdn.jsdelivr.net`,
  `fonts.googleapis.com`, `fonts.gstatic.com`, `unpkg.com`, `cdnjs.com`,
  `github.com`, or anything else outside your internal network.
- Apply the filter `-domain:${SITE_URL hostname}` — the list should be empty.
- Fonts render correctly (DM Sans + JetBrains Mono visible on headings and
  monospace blocks); if you see the system fallback, `vendor-fonts.sh`
  didn't run during build or the static files weren't collected.

This corresponds to the `{% if airgapped %}` branch in
`app/templates/base.html` — assets must come from `/static/app/vendor/`.

---

## 9. Phase H — Run the dedicated test suites

These are the automated tests that exist in the repo. Run them inside the
app container:

```bash
docker compose -f docker-compose.prod.yml exec app python -m pytest \
    tests/infrastructure/test_gitlab_client_closed_network.py \
    tests/infrastructure/test_sandbox_runner_kwargs.py \
    tests/presentation/test_login_provider_buttons.py \
    tests/management/ \
    -v
```

**Pass**: all green.

These confirm at the unit level what Phases C–G confirm at the system
level: GitLab client never reaches outside `INTERNAL_HOST`, sandbox runner
adds the CA mount + env when `CUSTOMER_CA_PATH` is set, login page renders
only the enabled providers, and the management commands behave on misuse.

---

## 10. Phase I — Failure-mode matrix

Provoke each of these once and confirm the failure is **loud and
actionable**, not silent. Revert each change before moving to the next.

| Break | Expected behavior |
|---|---|
| Unset `CUSTOMER_CA_PATH` and re-run `airgap_setup`. | Command exits non-zero, message names the missing variable. |
| Point `CUSTOMER_CA_PATH` at the **GitLab server cert** instead of the CA chain. | `airgap_smoketest` fails with a TLS verify error mentioning unknown issuer. |
| Set `SITE_URL=http://localhost` and re-run `airgap_setup`. | Rejected with a message about needing a public hostname. |
| Stop the local GitLab, then trigger a policy run. | Sandbox exits non-zero; `PolicyExecution.message` mentions connection failure (not an opaque `internal error`). |
| Skew the airgap host's clock by +2 years. | TLS handshake fails with "cert not yet valid" — confirms `docs/airgap.md` §7 (NTP). Reset the clock immediately after. |
| Set `SANDBOX_DNS=127.0.0.11` (Docker's embedded resolver, which gVisor cannot use). | Sandbox policies that resolve a hostname fail with NXDOMAIN; runner surfaces this in the execution result. |
| Remove `runsc` from the host runtime list (e.g. rename the binary) and trigger a run. | Runner falls back to default runtime, logs a `WARNING` line about gVisor unavailable, run still completes. |

---

## 11. Reporting

For each phase, record:
- ✅ / ❌ / ⚠️ outcome.
- Command transcripts (paste into the report).
- Screenshots of the login page (Phase D), the DevTools network panel
  (Phase G), and the policy result (Phase F).
- Any deviation from this plan and why.

A green run of Phases A–I is the bar for declaring the air-gap build
shippable to a customer site.
