# Quick Start

Get GitGrit running and your first policy evaluating in under 5 minutes.

## 1. Sign in

Go to [app.gitgrit.dev](https://app.gitgrit.dev) and sign in with your Google, GitHub, or GitLab account. A workspace is created automatically.

## 2. Connect a platform

Navigate to **Workspace Settings** and add a connection to your GitHub or GitLab instance:

1. Choose the platform (GitHub or GitLab)
2. Give it a display name (e.g., "My GitHub")
3. Provide a personal access token with `repo` scope (GitHub) or `read_api` scope (GitLab)

## 3. Add a project

Go to **Projects** → **Add Project**, select your connection, search for a repository, and add it. GitGrit automatically registers a webhook to receive events.

## 4. Create or install a policy

You can write your own policy or install one from the **Marketplace**:

- Go to **Marketplace** and click **Install** on any policy
- Or go to **Policies** → **New Policy** to write your own

## 5. Run policies

Policies run automatically on webhook events (push, pull request, etc.). You can also trigger them manually from the project page by clicking **Run All**.

## What's next?

- [Adding Projects](projects.md) — detailed guide on project setup
- [Writing Policies](policies.md) — learn the policy API
- [Policy Marketplace](../features/marketplace.md) — browse pre-built policies
