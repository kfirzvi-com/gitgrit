---
title: Cookies
---

# Cookies

*Effective 2026-11-26.*

The GitGrit app ([app.gitgrit.dev](https://app.gitgrit.dev)) uses only cookies that are **strictly necessary** to operate it. Our website ([gitgrit.dev](https://gitgrit.dev)) sets an analytics cookie **only if you accept it** (see [Website analytics](#website-analytics)). We do not run advertising or retargeting tools.

## Cookies the app sets

| Name | Purpose | Lifetime |
| --- | --- | --- |
| `sessionid` | Keeps you signed in across requests. Set after authentication. | Two weeks (Django default), refreshed on activity. |
| `csrftoken` | Protects form submissions and HTMX requests against cross-site request forgery. | One year. |

## OAuth provider cookies

When you sign in with Google, GitHub, or GitLab, those providers may set cookies on their own domains during the OAuth handshake. Their use is governed by their respective privacy policies.

## Website analytics

On [gitgrit.dev](https://gitgrit.dev) (not the app) we use PostHog, hosted in the EU, to see how the site is used. Your first visit shows a banner that asks whether you accept analytics cookies.

**Until you accept, or if you reject,** PostHog runs in cookieless mode: it sets no cookie and stores nothing on your device. Visits are counted with a hash of the IP address and browser, salted with a key that changes every day, so a visit can't be linked to you or to your visits on other days. The IP address itself is not stored.

**If you accept,** PostHog also sets the cookies below (on gitgrit.dev only; `<key>` is our PostHog project key), so your visits on different days are recognized as the same anonymous visitor, and records your session (mouse movements, clicks, scrolling, and the pages you see) so we can see where the site is confusing. Everything you type into a form field is masked and never recorded. We never link these records to your name or email address.

| Name | Purpose | Lifetime | Set when |
| --- | --- | --- | --- |
| `ph_<key>_posthog` (cookie and local storage) | Anonymous visitor and session ID for analytics and session replay. | One year. | Only after you accept. |
| `ph_<key>_posthog_cpm` (cookie) | PostHog's own bookkeeping for the cookie above. | One year. | Only after you accept. |
| `gg_consent` (local storage) | Remembers whether you accepted or rejected, so we don't ask on every page. Strictly necessary. | One year, then we ask again. | When you choose. |
| `__ph_opt_in_out_<key>` (local storage) | PostHog's copy of your choice, so it knows whether it may set cookies. Strictly necessary. | Until you clear site data. | When you choose. |

If you reject or withdraw consent, both `ph_` cookies and PostHog's local storage are deleted; only the two records of your choice remain. Data goes to PostHog through `e.gitgrit.dev`, a PostHog-operated address under our domain.

## Your choice

Accepting is optional, and rejecting is as easy as accepting: the site works the same either way. Change your mind at any time with **Cookie settings** in the site footer. If you withdraw consent, the analytics cookies are removed and we go back to counting your visits without cookies. You can also delete cookies and site data in your browser settings. We ask again after a year, or sooner if we change what this notice describes.

## Contact

Questions about this notice: [kfir@praktical.dev](mailto:kfir@praktical.dev).
