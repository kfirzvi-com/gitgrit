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

On [gitgrit.dev](https://gitgrit.dev) (not the app) we use PostHog, hosted in the EU, to see how the site is used. Your first visit shows a banner that asks whether you accept analytics.

**Until you accept, or if you reject,** no analytics runs: the PostHog script is not loaded, no request is sent to it, and nothing is stored on your device except your choice.

**If you accept,** PostHog loads and sets the items below (on gitgrit.dev only; `<key>` is our PostHog project key), so your visits on different days are recognized as the same anonymous visitor, and records your session (mouse movements, clicks, scrolling, and the pages you see) so we can see where the site is confusing. Everything you type into a form field is masked and never recorded. Your approximate location (country and region) is looked up from your IP address, and the IP address is then deleted before anything is stored. We never link these records to your name or email address.

| Name | Purpose | Lifetime | Set when |
| --- | --- | --- | --- |
| `ph_<key>_posthog` (cookie and local storage) | Anonymous visitor and session ID for analytics and session replay. | One year. | Only after you accept. |
| `ph_<key>_posthog_cpm` (cookie) | PostHog's own bookkeeping for the cookie above. | One year. | Only after you accept. |
| `ph_<key>_posthog__flags` (local storage) | PostHog's settings for this site, cached. | Until you reject or clear site data. | Only after you accept. |
| `__ph_opt_in_out_<key>` (local storage) | PostHog's copy of your choice. | Until you reject or clear site data. | Only after you accept. |
| `gg_consent` (local storage) | Remembers whether you accepted or rejected, so we don't ask on every page. Strictly necessary. | One year, then we ask again. | When you choose. |

If you reject or withdraw consent, all the `ph_` items above are deleted and PostHog no longer loads; only `gg_consent` remains. Data goes to PostHog through `e.gitgrit.dev`, a PostHog-operated address under our domain.

## Booking a demo

The **Book a demo** buttons open a booking form from Cal.com. Nothing from Cal.com loads until you click one. Once you do, Cal.com may set its own cookies needed to show and complete the booking; see [Cal.com's privacy policy](https://cal.com/privacy). We use them only because you asked to book.

## Everything else on gitgrit.dev

Fonts, scripts, and images are served from gitgrit.dev itself, so a page view sends nothing to Google, a CDN, or any other third party. The star count next to the GitHub link is fetched when we publish the site, not from your browser.

## Your choice

Accepting is optional, and rejecting is as easy as accepting: the site works the same either way. Change your mind at any time with **Cookie settings** in the site footer. You can also delete cookies and site data in your browser settings. We ask again after a year, or sooner if we change what this notice describes.

## Contact

Questions about this notice: [kfir@praktical.dev](mailto:kfir@praktical.dev).
