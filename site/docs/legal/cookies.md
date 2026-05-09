---
title: Cookies
---

# Cookies

*Effective 2026-05-04.*

GitGrit uses only cookies that are **strictly necessary** to operate the service. We do not run third-party analytics, advertising, retargeting, or session-replay tools.

## Cookies we set

| Name | Purpose | Lifetime |
| --- | --- | --- |
| `sessionid` | Keeps you signed in across requests. Set after authentication. | Two weeks (Django default), refreshed on activity. |
| `csrftoken` | Protects form submissions and HTMX requests against cross-site request forgery. | One year. |

## OAuth provider cookies

When you sign in with Google, GitHub, or GitLab, those providers may set cookies on their own domains during the OAuth handshake. Their use is governed by their respective privacy policies.

## Why no banner?

Under the EU ePrivacy Directive and the UK PECR, consent is required for cookies that are not strictly necessary. Because GitGrit only sets strictly-necessary cookies, no consent banner is shown. If we add analytics or marketing cookies in the future, we will add a consent flow before they fire.

## Contact

Questions about this notice: [kfir@kfirzvi.com](mailto:kfir@kfirzvi.com).
