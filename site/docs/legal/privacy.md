---
title: Privacy Policy
---

# Privacy Policy

*Effective 2026-11-26.*

## 1. About this notice

This Privacy Policy explains how Kfir Zvi, self-employed (autónomo) in Spain, NIF Z5107624L ("GitGrit", "we", "us") collects, uses, and shares personal data in connection with our website [gitgrit.dev](https://gitgrit.dev) and the hosted GitGrit service at [app.gitgrit.dev](https://app.gitgrit.dev) (the "Service"). It applies to website visitors, registered users, and people who book a demo. It does not apply to self-hosted deployments of GitGrit, which are controlled by the organization that runs them.

When your organization connects its repositories, GitGrit processes the personal data in them (for example, commit authors' names and email addresses) on your organization's behalf, as a processor under our [Data Processing Agreement](dpa.md). For that data your organization is the controller; contact it to exercise your rights.

## 2. Controller and contact

The controller is Kfir Zvi, self-employed (autónomo) in Spain, NIF Z5107624L, Calle Arquitectos Alamo y Ceballos 1, 26006 Logroño, La Rioja, Spain. Privacy contact: [kfir@praktical.dev](mailto:kfir@praktical.dev). We have not appointed a data protection officer, as the GDPR does not require one for our processing.

## 3. What we collect

- **Account data.** Email address, display name, avatar URL, and provider user ID returned by Google, GitHub, or GitLab during OAuth sign-in.
- **Workspace metadata.** Workspace name, membership roles, invitations, and API tokens you create.
- **Platform credentials.** Access tokens you provide for GitHub or GitLab connections. These are encrypted at rest with Fernet and used only to fetch repository data needed to evaluate the standards you have enabled.
- **Repository data.** Depending on which standards you have enabled, this may include repository metadata, file contents, commit history, member lists, and branch-protection settings, retrieved on demand to evaluate those standards. We do not browse repositories beyond what your standards request.
- **Webhook deliveries.** Push, pull-request, and tag events that your connected repositories deliver to GitGrit. These are consumed to trigger standard runs and are not stored as a separate record beyond what is captured in the resulting standard execution.
- **Standard execution records.** Inputs, outputs, status, score, and timing of each standard run.
- **Service logs.** IP address, user-agent, request path, and timestamps for security, debugging, and abuse prevention.
- **Support correspondence.** Messages you send to our support, security, or privacy mailboxes.
- **Website analytics and session replay (only with your consent).** If you accept analytics on [gitgrit.dev](https://gitgrit.dev), PostHog collects the pages you view, clicks, scroll depth, referrer, campaign (UTM) tags, approximate location (country and region), and browser and device type; stores an anonymous visitor ID in a cookie, so your visits on different days are linked to one another; and records your sessions on the site: mouse movements, clicks, scrolling, the pages you see, and browser console and network timings. Form inputs are masked and never recorded. Your approximate location is looked up from your IP address, and the IP address is then deleted before anything is stored. We never link this data to your name or email address. Until you accept, no analytics runs at all.
- **Demo bookings.** If you book a demo, the name, email address, time slot, and any notes you enter in the Cal.com booking form.

## 4. How and why we use it

We process personal data for the following purposes and on the following legal bases under the EU/UK GDPR. Where you are outside the EU/UK, an equivalent basis under your local law applies.

| Purpose | Legal basis |
| --- | --- |
| Provide the Service (account creation, standard execution, badges, API, CLI). | Performance of a contract with you or your organization. |
| Secure the Service (rate limiting, abuse detection, fraud prevention, audit logging). | Legitimate interests in keeping the Service available and trustworthy. |
| Operate, maintain, and improve the Service (debugging, performance tuning, aggregate usage analysis). | Legitimate interests in operating and improving the Service. |
| Understand how visitors find and use our website (website analytics and session replay). | Consent, which you can withdraw at any time with **Cookie settings** in the site footer. |
| Arrange and hold a demo you booked. | Steps taken at your request before entering into a contract. |
| Respond to support, security, or privacy requests. | Performance of a contract; legitimate interests; legal obligation where applicable. |
| Comply with law and respond to lawful requests. | Legal obligation. |

## 5. Sharing

We share personal data with the sub-processors listed on our [sub-processors page](sub-processors.md), each engaged under a written agreement that limits their use of the data to providing services to us. We share data with law-enforcement or government bodies only when required by a binding legal request or to protect the rights, property, or safety of GitGrit, our users, or the public. We do not sell personal data and we do not use it for advertising or to train third-party AI models.

## 6. International transfers

The Service is hosted in the European Union (AWS region `eu-north-1`, Stockholm, Sweden). Some sub-processors are located in the United States or operate global edge networks. Where personal data is transferred outside the European Economic Area or the United Kingdom, we rely on an adequacy decision (including the EU–US Data Privacy Framework, for recipients certified under it) or on the European Commission's Standard Contractual Clauses (and the UK Addendum where applicable) and apply supplementary technical measures — including encryption of access tokens at rest and TLS in transit — informed by a transfer-impact assessment. You may request a copy of the relevant transfer mechanism by emailing [kfir@praktical.dev](mailto:kfir@praktical.dev).

## 7. Retention

- **Account data.** Kept while the account is active. Deleted or anonymized within thirty (30) days of account closure, subject to the backup window in §8.
- **Encrypted access tokens.** Kept only while the connection exists; deleted when you remove the connection.
- **Repository data fetched for evaluation.** Cached only as long as needed to complete a standard run; not persisted in raw form.
- **Webhook deliveries.** Not retained as a separate record; the resulting standard execution record applies (see below).
- **Standard execution records.** Twelve (12) months, after which they are aggregated for trend analysis without identifying individuals.
- **Service logs.** Thirty (30) days.
- **Security audit logs.** Twelve (12) months for integrity and incident-investigation purposes.
- **Support correspondence.** Twenty-four (24) months from the last message in the thread.
- **Website analytics.** Twelve (12) months.
- **Demo bookings.** Twenty-four (24) months from the meeting, unless it leads to a contract.
- **Session replays.** Thirty (30) days.

## 8. Backups

Backups containing personal data are retained for up to ninety (90) days in encrypted form. Deletions of live data propagate to backups on the next backup-rotation cycle within that window.

## 9. Your rights

Under the GDPR and Spain's Organic Law 3/2018 (LOPDGDD) you have the right to: access your personal data; correct inaccurate data; have your data erased; restrict processing; object to processing based on legitimate interests; receive your data in a portable format; and withdraw consent at any time, without affecting processing carried out before you withdrew it. To exercise any of these rights, email [kfir@praktical.dev](mailto:kfir@praktical.dev). We respond within one month; we may ask you to confirm your identity first.

You also have the right to lodge a complaint with a supervisory authority. Our lead authority is the Spanish Data Protection Agency (Agencia Española de Protección de Datos, C/ Jorge Juan 6, 28001 Madrid, [www.aepd.es](https://www.aepd.es)). You may also complain to the authority where you live or work.

## 10. Cookies

The Service sets only cookies that are strictly necessary to operate it. Our website runs analytics and sets analytics cookies only if you accept them, and you can withdraw that consent at any time with **Cookie settings** in the site footer. See our [cookies notice](cookies.md) for the full list and lifetimes.

## 11. Security

We apply technical and organizational measures appropriate to the risk, including: encryption of platform access tokens at rest with Fernet; TLS for data in transit; HMAC verification of incoming webhooks; gVisor-sandboxed execution of standard code; least-privilege role assignments; and security logging. Our threat model and disclosure process are documented in [SECURITY.md](https://github.com/kfirzvi-com/gitgrit/blob/main/SECURITY.md). No system is perfectly secure; we cannot guarantee that personal data will never be compromised.

## 12. Children

The Service is not directed at children under sixteen (16), and we do not knowingly collect personal data from them. If you believe we have inadvertently collected data from a child, contact [kfir@praktical.dev](mailto:kfir@praktical.dev) and we will delete it.

## 13. Automated decision-making

The Service evaluates repositories against standards you have enabled and produces a compliance score. These results are informational; we do not make decisions that produce legal or similarly significant effects on individuals based solely on automated processing.

## 14. AI integrations

The Service offers a public API and command-line tool that third-party large-language-model clients can use to read GitGrit data and propose standard edits. When you connect such a client, the prompts and the data it reads are transmitted to the model provider you have configured under that provider's terms and privacy policy. GitGrit itself does not send user data to any AI provider for training.

## 15. Changes to this notice

We may update this Privacy Policy from time to time. The "Effective" date at the top reflects the current version. We will announce material changes at least thirty (30) days before they take effect via the Service or by email to the address on file.
