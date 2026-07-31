---
name: deploy
description: How to deploy GitGrit — Kamal 2 deploy commands, CI/CD flow, and generating/handling SECRET_KEY and GITGRIT_ENCRYPTION_KEY. Use when deploying, configuring Kamal, setting up servers, or rotating deployment secrets.
---

# Deploying GitGrit

- **Domain:** gitgrit.dev
- **Deployment tool:** Kamal 2 (config in `config/deploy.yml`)
- **Production:** Gunicorn + WhiteNoise behind Kamal proxy
- **Registry:** GHCR (`ghcr.io/kfirzvi-com/gitgrit`)

## CI/CD
- **On PR:** tests run via `.github/workflows/ci.yml`
- **On merge to main:** image built + pushed to GHCR, auto-deploys to staging
- **On tag `v*`:** image built + pushed to GHCR, auto-deploys to production
- **Manual:** `workflow_dispatch` on publish.yml to deploy a branch to staging
- Deploy is handled by the `kfirzvi-com/infra` repo (receives `repository_dispatch`)

## Kamal Config
- `config/deploy.yml` — base config (tracked, public). Uses GHCR registry.
- `config/deploy.<dest>.yml` — destination overrides with server IPs/domains (gitignored, lives in infra repo for CI)
- `.kamal/secrets.<dest>` — secrets (gitignored). `SECRET_KEY` and `GITGRIT_ENCRYPTION_KEY` must be static (not generated per deploy). Rotating either invalidates stored OAuth tokens.
- `.kamal/hooks/docker-setup` — installs gVisor on servers. Runs locally, SSHes into servers via `$KAMAL_HOSTS`.

## Local Deploy
```bash
# First time
kamal setup -d <destination>

# Subsequent deploys
kamal deploy -d <destination>

# Reboot proxy (after Kamal upgrade)
kamal proxy reboot -d <destination> -y
```

## Generate a SECRET_KEY
```bash
cat /dev/urandom | LC_ALL=C tr -dc 'a-zA-Z0-9' | fold -w 50 | head -n 1
```

## Generate a GITGRIT_ENCRYPTION_KEY
```bash
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
Used by `app.infrastructure.encryption` to encrypt `PlatformConnection.access_token` at rest with Fernet. In `DEBUG=True` local dev a key is derived from `SECRET_KEY` automatically; production deploys require `GITGRIT_ENCRYPTION_KEY` explicitly so that rotating `SECRET_KEY` does not orphan stored ciphertext.
