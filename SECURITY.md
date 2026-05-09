# Security Policy

GitGrit's threat surface is unusually wide for an open-source web app: it executes user-supplied code in a sandbox, holds OAuth tokens for GitHub and GitLab, exposes webhook endpoints, and ships an MCP server that LLM clients drive. This document describes what is in place today, what is explicitly *not*, and how to report vulnerabilities.

## Reporting a vulnerability

**Please do not open a public GitHub issue.** Use one of:

1. **GitHub Private Vulnerability Reporting** — preferred. From the [Security tab](https://github.com/kfirzvi-com/gitgrit/security/advisories/new) on this repo, click *Report a vulnerability*.
2. **Email** — `kfir@kfirzvi.com`.

We will acknowledge receipt within **3 business days**, give you an initial triage assessment within **7 business days**, and aim to ship a fix within **30 days** for critical severity. We follow coordinated disclosure: publish a fix, then a CVE/advisory, then credit the reporter (unless they prefer to remain anonymous).

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
- Sandbox escape from a malicious policy (`sandbox_image/`, `app/infrastructure/sandbox/`)
- OAuth token leakage from `PlatformConnection` (database, logs, error pages, admin views)
- Tenancy isolation bypass in the MCP server (`app/infrastructure/mcp/`) or the web app
- Authentication bypass on any non-public endpoint
- Stored XSS or SSRF reachable via policy code, MCP tool input, or webhook payloads
- Privilege escalation within a workspace (member → admin → owner)

### Out of scope
- Denial-of-service via unrealistic load (we run a single VM in production; please don't)
- Self-XSS or attacks requiring a victim to paste content into their own browser console
- Reports against unsupported versions
- Vulnerabilities in third-party dependencies that have a published advisory but no patch yet
- Anything reachable only by a workspace owner against their own workspace

## Threat model

### Sandbox isolation (policy execution)

Every policy is user-authored Python that runs against a `ProjectContext` exposing the repo's files, languages, and metadata. We assume the policy code is **untrusted**.

**Defenses:**
- Each policy runs in a **fresh Docker container** built from `sandbox_image/`, with `cap_drop: ["ALL"]`, no Linux capabilities, and a 30-second wall-clock timeout. Memory is capped at 128 MB and CPU at 0.5 cores.
- The runtime is configured as **gVisor (`runsc`)**. See `app/infrastructure/sandbox/runner.py`.
- Policy code is bind-mounted **read-only** at `/policy.py`; the only writable filesystem is a 16 MB tmpfs at `/tmp`.
- Network access is restricted to a custom Docker bridge that allows outbound HTTPS to platform APIs but blocks the host network and other containers.

**Known limitations:**
- If `runsc` is not installed on the host, the runner **falls back to the default Docker runtime (runc)** with a warning log. `runc` provides container isolation but not the syscall-level sandbox gVisor offers — operators must verify gVisor is installed (the `.kamal/hooks/docker-setup` hook handles this on production deploys; self-hosters must do it themselves).
- The container runs as **root** inside the namespace. Capabilities are dropped, but a root-in-namespace + missing-gVisor combination is meaningfully weaker than non-root + gVisor. **Setting a non-root `USER` in `sandbox_image/Dockerfile` is a planned hardening.**
- There is **no PID limit** on the container. A fork-bomb policy will be killed by the timeout but can briefly stress the host.
- Fernet-style key rotation for sandbox-passed tokens is not implemented; a long-lived OAuth token leaked from a sandbox compromise stays valid until manually revoked.

### Webhook ingress

`/api/webhooks/github/` and `/api/webhooks/gitlab/` accept events from third parties.

**Defenses:**
- **GitHub**: `X-Hub-Signature-256` is verified as HMAC-SHA256 of the raw request body using the per-`Project` `webhook_secret` (`app/presentation/views/base_webhook.py`, `app/infrastructure/webhook_signatures.py`). Comparison is constant-time (`hmac.compare_digest`).
- **GitLab**: `X-Gitlab-Token` is constant-time-compared against the per-`Project` `webhook_secret`.
- Each `Project` registered through the UI gets a fresh 32-byte hex secret; that secret is sent to the platform when the webhook is created and stored locally.
- Signature mismatch → **HTTP 401**. The signature is verified before any policy is run.

**Known limitations:**
- For backward compatibility with v0.1 projects that predate signature verification, projects with an empty `webhook_secret` are accepted unsigned with a warning log. Operators with such projects should re-register the webhook (the UI generates a fresh secret) or run a backfill. **This relaxation will be removed in a future release** — flip the `unsecured` branch in `BaseWebhookView._verify_signature` to return `"rejected"` once all projects in your install have a secret.
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

### MCP server

`app/infrastructure/mcp/` exposes an authenticated MCP endpoint at `/mcp/`. LLM clients (Claude Code, Cline, Cursor, generic MCP-aware tools) call its tools to read project state and, with the right token, mutate policies.

**Defenses:**
- All tools require `Authorization: Bearer <token>` via `app/infrastructure/mcp/middleware.py`. Tokens are SHA-256 hashed at rest in `APIToken.token_hash` (raw token never stored).
- Each token belongs to a (user, tenant) pair via FKs on the `APIToken` model. Tool calls are scoped to that tenant.
- Read-only tools: `validate_edit`, `validate_action`, `list_policies`, `get_policy`, `list_projects`, `resolve_project`, `get_project_status`, `get_active_policies_for_project`, `session_bootstrap`, `run_policy_test`, `export_setup_files`, `get_project_context_api`.
- Write-capable tools: `create_policy`, `update_policy`, `delete_policy`, `set_policy_code`. These mutate workspace state and should only be granted to tokens issued for trusted clients.

**Known limitations:**
- **All tools are accessible from any valid token.** There is no per-tool scope (no read-only token kind). If an LLM client receives a token, it can create or delete policies in that user's tenant. Treat MCP tokens as workspace-write-capable until per-token scopes ship.
- Tool inputs may contain text from PR diffs. **An LLM driving the MCP server is exposed to prompt injection from untrusted PR content.** Mitigations: do not let the LLM auto-merge or auto-deploy based on tool outputs; require human review for any write tool the LLM chains into.
- `run_policy_test` executes user-supplied policy code in the sandbox with mock data. The same sandbox guarantees and limitations described above apply.

### API tokens

User-issued API tokens (`APIToken` model) authenticate the MCP server and external HTTP API.

**Defenses:**
- Generated via `secrets.token_urlsafe(32)` with a `grit_` prefix (~48 raw chars total).
- Stored as **SHA-256 hash** (`token_hash`); only the first 12 chars are kept verbatim as a `prefix` for UI display. Compromising the database does not yield raw tokens.
- Lookup is by hash equality; rate-limiting is handled by the upstream proxy.

**Known limitations:**
- No expiry, no rotation reminder. Tokens are valid until manually revoked.
- No per-tool scope (see MCP section).

## Follow-ups tracked against this document

These are known gaps the project intends to close. Filing an issue or PR for any of them is welcome.

- Set a non-root `USER` in `sandbox_image/Dockerfile`.
- Add a `pids_limit` to the sandbox container.
- Hard-fail at startup if `runsc` is not registered as a Docker runtime (today: warning log + silent fallback).
- Tighten `BaseWebhookView._verify_signature` to return `"rejected"` for empty-secret projects (today: `"unsecured"` + warning).
- Add a `GITGRIT_ENCRYPTION_STRICT=1` flag that disables the lenient legacy-plaintext read path on `EncryptedCharField`, plus a management command that asserts every row is ciphertext before flipping the flag.
- Implement key rotation via `cryptography.fernet.MultiFernet`.
- Encrypt `socialaccount_socialtoken` rows (Google OAuth) the same way `PlatformConnection.access_token` is encrypted.
- Add per-token scopes (read-only vs write) for MCP tokens.
- Add a token-expiry field and surface "stale token" warnings in the UI.
