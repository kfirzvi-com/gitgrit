# Security Policy

GitGrit's threat surface is unusually wide for an open-source web app: it executes user-supplied code in a sandbox, holds OAuth tokens for GitHub and GitLab, exposes webhook endpoints, and serves a public REST API that scripts, CI pipelines and AI agents drive. This document describes what is in place today, what is explicitly *not*, and how to report vulnerabilities.

## Reporting a vulnerability

**Please do not open a public GitHub issue.** Use one of:

1. **GitHub Private Vulnerability Reporting** — preferred. From the [Security tab](https://github.com/kfirzvi-com/gitgrit/security/advisories/new) on this repo, click *Report a vulnerability*.
2. **Email** — `kfir@kfirzvi.com`.

These contacts are also published at `https://app.gitgrit.dev/.well-known/security.txt`.

GitGrit is maintained on a best-effort basis without a dedicated security on-call, so we cannot commit to specific response, triage, or fix timelines. We aim to work through reports as quickly as we reasonably can. We follow coordinated disclosure where practical: ship a fix, then a CVE/advisory, then credit the reporter (unless they prefer to remain anonymous).

If you would like to encrypt your report, request our PGP key at the same address.

## Supported versions

GitGrit is pre-1.0 and ships from a single `main` branch. We currently support security fixes for:

| Version | Supported |
|---------|-----------|
| latest tagged release | yes |
| previous tagged release | yes — security fixes only |
| older releases | no — please upgrade |
| `main` between tags | use at your own risk; security fixes land here first |

## Scope

### In scope
- Webhook signature bypass on `/api/webhooks/github/` and `/api/webhooks/gitlab/`
- Sandbox escape from a malicious standard (`sandbox_image/`, `app/infrastructure/sandbox/`)
- OAuth token leakage from `PlatformConnection` (database, logs, error pages, admin views)
- Tenancy isolation bypass in the public API (`app/presentation/api/`) or the web app
- Authentication bypass on any non-public endpoint
- Stored XSS or SSRF reachable via standard code, API input, or webhook payloads
- Privilege escalation within a workspace (member → admin → owner)

### Out of scope
- Denial-of-service via unrealistic load (we run a single VM in production; please don't)
- Self-XSS or attacks requiring a victim to paste content into their own browser console
- Reports against unsupported versions
- Vulnerabilities in third-party dependencies that have a published advisory but no patch yet
- Anything reachable only by a workspace owner against their own workspace

## Threat model

### Sandbox isolation (standard execution)

Every standard is user-authored Python that runs against a `ProjectContext` exposing the repo's files, languages, and metadata. We assume the standard code is **untrusted**.

**Defenses:**
- Each standard runs in a **fresh Docker container** built from `sandbox_image/`, with `cap_drop: ["ALL"]`, no Linux capabilities, and a 30-second wall-clock timeout. Memory is capped at 128 MB and CPU at 0.5 cores.
- The runtime is configured as **gVisor (`runsc`)**. See `app/infrastructure/sandbox/runner.py`.
- Standard code is bind-mounted **read-only** at `/standard.py`; the only writable filesystem is a 16 MB tmpfs at `/tmp`.
- Network access is restricted to a custom Docker bridge that allows outbound HTTPS to platform APIs but blocks the host network and other containers.

**Known limitations:**
- If `runsc` is not installed on the host, the runner **falls back to the default Docker runtime (runc)** with a warning log. `runc` provides container isolation but not the syscall-level sandbox gVisor offers — operators must verify gVisor is installed (the `.kamal/hooks/docker-setup` hook handles this on production deploys; self-hosters must do it themselves).
- The container runs as **root** inside the namespace. Capabilities are dropped, but a root-in-namespace + missing-gVisor combination is meaningfully weaker than non-root + gVisor. **Setting a non-root `USER` in `sandbox_image/Dockerfile` is a planned hardening.**
- There is **no PID limit** on the container. A fork-bomb standard will be killed by the timeout but can briefly stress the host.
- Fernet-style key rotation for sandbox-passed tokens is not implemented; a long-lived OAuth token leaked from a sandbox compromise stays valid until manually revoked.
- **Runs of a standard get the workspace's LLM API keys, and real runs the repository token too, whoever wrote it.** Any workspace member can save or test-run a standard, and the sandbox has network access, so a member's code can send those keys out. Limit workspace membership to people you trust with those keys. Whether to give keys only to admin-approved standards is an open product decision.

### Webhook ingress

`/api/webhooks/github/` and `/api/webhooks/gitlab/` accept events from third parties.

**Defenses:**
- **GitHub**: `X-Hub-Signature-256` is verified as HMAC-SHA256 of the raw request body using the per-`Project` `webhook_secret` (`app/presentation/views/base_webhook.py`, `app/infrastructure/webhook_signatures.py`). Comparison is constant-time (`hmac.compare_digest`).
- **GitLab**: `X-Gitlab-Token` is constant-time-compared against the per-`Project` `webhook_secret`.
- Each `Project` registered through the UI gets a fresh 32-byte hex secret; that secret is sent to the platform when the webhook is created and stored locally.
- Signature mismatch → **HTTP 401**. The signature is verified before any standard is run.

**Known limitations:**
- For backward compatibility with v0.1 projects that predate signature verification, projects with an empty `webhook_secret` are accepted unsigned with a warning log. Operators with such projects should re-register the webhook (the UI generates a fresh secret) or run a backfill. **This relaxation is intended to be removed in a future release on a best-effort basis** — flipping the `unsecured` branch in `BaseWebhookView._verify_signature` to return `"rejected"` once all projects in your install have a secret. No specific timeline is committed.
- The signature is verified against the secret of any tenant that has registered this `external_id`. In a multi-tenant install where two tenants register the same external repo, a forged request signed with either tenant's secret will validate. This matches how the platforms send hooks (each tenant has its own webhook with its own secret), but be aware of it.

### OAuth token storage

GitGrit stores GitHub and GitLab personal access tokens on `PlatformConnection.access_token` so the sandbox runner can call platform APIs on the user's behalf.

**Defenses:**
- Tokens are stored as **Fernet ciphertext** (AES-128-CBC + HMAC-SHA256, 128-bit IV) via `app.infrastructure.model_fields.EncryptedCharField`. See `app/infrastructure/encryption.py`.
- The encryption key is read from `GITGRIT_ENCRYPTION_KEY` (a urlsafe-base64-encoded 32-byte Fernet key). In `DEBUG=True` development a key is derived from `SECRET_KEY`; production deployments must set `GITGRIT_ENCRYPTION_KEY` explicitly, so rotating `SECRET_KEY` does not orphan ciphertext.
- The Django admin hides the raw token field on the edit page (`app/admin.py:55-60`).
- Tokens leave the database only to be passed into the sandbox container at runtime, written to a read-only `/input.json` mount, and consumed by the platform-client provider. They are never logged.

**Known limitations:**
- `EncryptedCharField` reads are currently lenient toward legacy plaintext (returns the value verbatim with a warning log). This supports the rolling migration that re-encrypts existing rows on save and **must be tightened to strict mode** once all installs have migrated.
- No key-rotation support yet. `cryptography.fernet.MultiFernet` is the planned path. Until it lands, rotating `GITGRIT_ENCRYPTION_KEY` requires manually re-saving every `PlatformConnection`.
- Google OAuth tokens stored by `django-allauth` in `socialaccount_socialtoken` are **not** encrypted — they are subject to allauth's defaults. The Google scopes we request (`profile`, `email`) are sign-in only, but you should still treat that table as sensitive in your DB backup posture.
- The sandbox provider receives the **plaintext** token via the `/input.json` mount. A sandbox escape is therefore equivalent to OAuth token disclosure for that connection. Sandbox-side token exposure is mitigated by gVisor (see above) but not eliminated.

### Public API

`app/presentation/api/` serves the REST API at `/api/v1/` (OpenAPI document at `/api/v1/schema/`). Every workspace-scoped call names its workspace in the URL: `/api/v1/workspaces/{id}/...`.

**Defenses:**
- Every endpoint requires `Authorization: Bearer <token>`; browser sessions are not accepted, so the API needs no CSRF exemption.
- The workspace in the URL is checked on every call: a user (OAuth or personal token) must be a member; a workspace token must belong to it. Anything else is a 404, so workspace ids can't be probed.
- Write endpoints (create/update/delete standards, run checks) need the `write` OAuth scope; reads need `read`.

**Known limitations:**
- Any member can manage standards through the API, as in the web app; there is no role check beyond membership.
- `POST .../standards/test/` executes user-supplied standard code in the sandbox with mock data. The sandbox defenses and limitations above apply.
- API responses may contain text from PR diffs and repository files. **An LLM agent driving the API is exposed to prompt injection from that content.** Don't let it auto-merge or auto-deploy based on API output; require human review for any write it chains into.

### OAuth (CLI sign-in)

The `gitgrit` CLI signs in with OAuth 2.0 via [django-oauth-toolkit](https://github.com/jazzband/django-oauth-toolkit): authorization code + PKCE (S256 only) with an RFC 8252 loopback redirect, for the public client `gitgrit-cli` (registered by migration; no client secret). Only `/oauth/authorize/`, `/oauth/token/`, `/oauth/revoke_token/` and `/.well-known/oauth-authorization-server` are mounted — DOT's application-management views are not.

**Defenses:** access tokens expire after an hour; refresh tokens rotate and a reused refresh token is rejected; tokens are stored hashed (RFC 9700); the implicit and password grants are refused; the authorization response carries `iss` (RFC 9207). Tokens belong to a user and can reach every workspace that user is a member of.

**Known limitations:** there is no page yet to list or revoke OAuth sign-ins; `gitgrit auth logout` revokes its own. Expired tokens are not purged until `manage.py cleartokens` runs.

### API tokens

Long-lived `APIToken`s, for scripts and CI/CD. Two kinds:

- **Personal** (`grit_pat_…`, profile page): acts as its user, in every workspace they're a member of. Dies with the user's membership or account; refused once the user is deactivated.
- **Workspace** (`grit_ws_…`, workspace settings, admins only): reaches one workspace and has no user behind it, so it survives its creator leaving. Changes it makes are recorded with no user.

**Defenses:**
- Generated via `secrets.token_urlsafe(32)` behind the kind's prefix.
- Stored as **SHA-256 hash** (`token_hash`); only the first 16 chars are kept as a `prefix` for UI display. Compromising the database does not yield raw tokens.
- Lookup is by hash equality; rate-limiting is handled by the upstream proxy.

**Known limitations:**
- No expiry, no rotation reminder. Tokens are valid until revoked.
- No scopes: an API token has its owner's full access.

## Follow-ups tracked against this document

These are known gaps the project intends to close. Filing an issue or PR for any of them is welcome.

- Set a non-root `USER` in `sandbox_image/Dockerfile`.
- Add a `pids_limit` to the sandbox container.
- Hard-fail at startup if `runsc` is not registered as a Docker runtime (today: warning log + silent fallback).
- Tighten `BaseWebhookView._verify_signature` to return `"rejected"` for empty-secret projects (today: `"unsecured"` + warning).
- Add a `GITGRIT_ENCRYPTION_STRICT=1` flag that disables the lenient legacy-plaintext read path on `EncryptedCharField`, plus a management command that asserts every row is ciphertext before flipping the flag.
- Implement key rotation via `cryptography.fernet.MultiFernet`.
- Encrypt `socialaccount_socialtoken` rows (Google OAuth) the same way `PlatformConnection.access_token` is encrypted.
- Add scopes (read-only vs write) for API tokens, as OAuth tokens already have.
- Add a token-expiry field and surface "stale token" warnings in the UI.
- Workspace invitation tokens travel in the emailed link's path (`/invitations/<token>/`), so the web server's access log records them on the first visit, and again on the accept/decline posts. Only a hash is stored, a token is single-use and expires, and the page sends no `Referer`. Moving the token out of the path (e.g. a POST from the landing page) would close this.
