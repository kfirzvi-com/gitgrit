# GitGrit — Claude Code Instructions

GitGrit is a DevOps compliance and best practices enforcement platform designed to streamline, automate, and scale DevOps adoption across organizations.

## Local Dev Commands

```bash
# Start database
docker compose up -d

# Install dependencies
uv sync

# Run migrations
uv run python manage.py migrate

# Run dev server
uv run python manage.py runserver
```

## Deployment

For Kamal deploy commands, the CI/CD flow, and `SECRET_KEY` / `GITGRIT_ENCRYPTION_KEY` handling (including the gotcha that rotating either invalidates stored OAuth tokens), see the **`deploy` skill** (`.claude/skills/deploy/SKILL.md`).
