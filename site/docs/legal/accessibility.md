---
title: Accessibility statement
---

# Accessibility statement

*Effective 2026-05-04.*

GitGrit is committed to making its services usable for as many people as possible. We aim to conform with the [Web Content Accessibility Guidelines 2.1, level AA](https://www.w3.org/TR/WCAG21/). This statement reflects the current state honestly — including known gaps — rather than aspirational claims.

## Conformance status

GitGrit is **partially conformant** with WCAG 2.1 AA. Some parts of the application do not yet meet the criteria; those are listed below.

## Known limitations

- **Dark theme only.** The interface ships with a single dark theme. Users who require a high-contrast or light theme cannot currently switch within the app and must rely on operating-system or browser-level contrast adjustments.
- **Loading splash hides main content.** Pages briefly hide the `<main>` element while client-side assets load. On slow connections this can delay screen-reader users perceiving page content for up to a second.
- **HTMX-driven updates.** Some interactions update the page without a full reload. Live-region announcements are not yet wired for every dynamic update; assistive technology users may need to re-navigate to perceive new content.
- **Charts and analytics.** Dashboard charts on the analytics tab convey information primarily through color and visual position. A tabular fallback is on the roadmap.
- **Third-party assets.** When not running in airgapped mode, DaisyUI, Tailwind, HTMX, and Google Fonts load from CDNs. Network conditions can affect first paint.

## Compatibility

GitGrit is designed to work with current versions of Chrome, Firefox, Safari, and Edge, and with the assistive technologies bundled with macOS, iOS, Windows, and Android. Internet Explorer is not supported.

## Feedback

We welcome feedback on accessibility barriers. Please email [kfir@kfirzvi.com](mailto:kfir@kfirzvi.com) with a description of the issue, the page URL, and the assistive technology you are using. We aim to respond within ten business days.

## Assessment

This statement is based on a self-assessment by the GitGrit team. It will be updated as gaps are closed and as the application evolves.
