---
title: Sub-processors
---

# Sub-processors

*Effective 2026-05-04.*

A sub-processor is a third party engaged by GitGrit that processes customer personal data in connection with the service. The list below reflects the production hosted service at [app.gitgrit.dev](https://app.gitgrit.dev). Self-hosted deployments do not involve these sub-processors.

## Current sub-processors

| Sub-processor | Purpose | Location |
| --- | --- | --- |
| Amazon Web Services, Inc. | Application hosting and managed PostgreSQL database. | <mark class="legal-placeholder">[Hosting region]</mark> |
| GitHub, Inc. — Container Registry | Hosting of GitGrit container images used during deployment. | United States |
| GitHub, Inc. — OAuth & REST API | OAuth sign-in and repository data access for connected GitHub projects. | United States |
| GitLab Inc. | OAuth sign-in and repository data access for connected GitLab projects. | United States |
| Google LLC — OAuth | OAuth sign-in for users authenticating with a Google account. | United States |
| Google LLC — Fonts | CDN delivery of typefaces used by the web UI. | Global edge |
| Public CDNs (jsDelivr, unpkg) | Delivery of front-end libraries (DaisyUI, Tailwind, HTMX) when the application is not running in airgapped mode. No personal data is submitted; the CDN sees the visitor's IP address and user-agent. | Global edge |

## Optional sub-processors

The following sub-processors are engaged only if the corresponding feature is used:

| Sub-processor | Engaged when |
| --- | --- |
| Anthropic PBC (Claude API) | A user connects an MCP client (e.g. Claude Code) and that client sends prompts containing GitGrit data to Anthropic. GitGrit itself does not transmit data to Anthropic. |

## Notice of new sub-processors

We will update this page before adding a new sub-processor. Customers on a written agreement that requires advance notice will be notified via the contact on file. To subscribe to changes, email [privacy@gitgrit.dev](mailto:privacy@gitgrit.dev).
