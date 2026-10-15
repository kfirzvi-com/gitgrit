# Quick Start

Get GitGrit running and your first standard evaluating in under 5 minutes.

## 1. Get access

GitGrit is invite-only for now. Go to [app.gitgrit.dev](https://app.gitgrit.dev) and sign in with your Google, GitHub, or GitLab account, or enter an email and password. With an email and password, confirm your address from the email we send first. If you're new, you'll be asked a few questions about you and your team, and your request goes to the GitGrit team.

Once approved, you get an email and join your company's workspace. The first person from a company owns it; see [Workspaces & Members](workspaces.md) for what each role can do.

## 2. Connect a platform

Navigate to **Workspace Settings** and add a connection to your GitHub or GitLab instance:

1. Choose the platform (GitHub or GitLab)
2. Give it a display name (e.g., "My GitHub")
3. Provide a personal access token — click **"How to generate a token?"** for platform-specific instructions and required permissions

## 3. Add a project

Go to **Projects** → **Add Project**, select your connection, search for a repository, and add it. GitGrit automatically registers a webhook to receive events.

## 4. Create or install a standard

You can write your own standard or install one from the **Marketplace**:

- Go to **Marketplace** and click **Install** on any standard
- Or go to **Standards** → **New Standard** to write your own

## 5. Run standards

Standards run automatically on webhook events (push, pull request, etc.). You can also trigger them manually from the project page by clicking **Run All**. Runs execute in the background: each standard shows as *Running* on the project page and the results fill in as they finish.

## What's next?

- [Workspaces & Members](workspaces.md) — roles, inviting people, deleting a workspace
- [Adding Projects](projects.md) — detailed guide on project setup
- [Writing Standards](standards.md) — learn the standard API
- [Standard Marketplace](../features/marketplace.md) — browse pre-built standards
