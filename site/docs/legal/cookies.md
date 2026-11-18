---
title: Cookies
---

# Cookies

*Effective 2026-11-18.*

GitGrit uses only cookies that are **strictly necessary** to operate the service. We do not run advertising, retargeting, or session-replay tools, and the website analytics we use sets no cookies (see [Website analytics](#website-analytics)).

## Cookies we set

| Name | Purpose | Lifetime |
| --- | --- | --- |
| `sessionid` | Keeps you signed in across requests. Set after authentication. | Two weeks (Django default), refreshed on activity. |
| `csrftoken` | Protects form submissions and HTMX requests against cross-site request forgery. | One year. |

## OAuth provider cookies

When you sign in with Google, GitHub, or GitLab, those providers may set cookies on their own domains during the OAuth handshake. Their use is governed by their respective privacy policies.

## Website analytics

On [gitgrit.dev](https://gitgrit.dev) (not the app) we use PostHog, hosted in the EU, in cookieless mode to count visits and see which pages are read. It sets no cookies and stores nothing on your device. Visits are counted with a hash of the IP address and browser, salted with a key that changes every day, so a visit can't be linked to you or to your visits on other days. The IP address itself is not stored.

## Why no banner?

Under the EU ePrivacy Directive and the UK PECR, consent is required for cookies that are not strictly necessary. Because GitGrit only sets strictly-necessary cookies, and our website analytics stores nothing on your device, no consent banner is shown. If we add analytics or marketing cookies in the future, we will add a consent flow before they fire.

## Contact

Questions about this notice: [kfir@praktical.dev](mailto:kfir@praktical.dev).
