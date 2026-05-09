---
title: Privacy Policy
---

# Privacy Policy

*Effective 2026-05-04.*

## 1. About this notice

This Privacy Policy explains how <mark class="legal-placeholder">[Operator legal name]</mark> ("GitGrit", "we", "us") collects, uses, and shares personal data in connection with the hosted GitGrit service at [app.gitgrit.dev](https://app.gitgrit.dev) (the "Service"). It applies to visitors, registered users, and people whose data is processed because their organization uses the Service. It does not apply to self-hosted deployments of GitGrit, which are controlled by the organization that runs them.

## 2. Controller and contact

The controller of personal data processed through the Service is <mark class="legal-placeholder">[Operator legal name]</mark>, <mark class="legal-placeholder">[Operator registered address]</mark>. Privacy contact: [privacy@gitgrit.dev](mailto:privacy@gitgrit.dev).

## 3. What we collect

- **Account data.** Email address, display name, avatar URL, and provider user ID returned by Google, GitHub, or GitLab during OAuth sign-in.
- **Workspace metadata.** Workspace name, membership roles, invitations, and API tokens you create.
- **Platform credentials.** Access tokens you provide for GitHub or GitLab connections. These are encrypted at rest with Fernet and used only to fetch repository data needed to evaluate the policies you have enabled.
- **Repository data.** Depending on which policies you have enabled, this may include repository metadata, file contents, commit history, member lists, and branch-protection settings, retrieved on demand to evaluate those policies. We do not browse repositories beyond what your policies request.
- **Webhook deliveries.** Push, pull-request, and tag events that your connected repositories deliver to GitGrit. These are consumed to trigger policy runs and are not stored as a separate record beyond what is captured in the resulting policy execution.
- **Policy execution records.** Inputs, outputs, status, score, and timing of each policy run.
- **Service logs.** IP address, user-agent, request path, and timestamps for security, debugging, and abuse prevention.
- **Support correspondence.** Messages you send to our support, security, or privacy mailboxes.

## 4. How and why we use it

We process personal data for the following purposes and on the following legal bases under the EU/UK GDPR. Where you are outside the EU/UK, an equivalent basis under your local law applies.

| Purpose | Legal basis |
| --- | --- |
| Provide the Service (account creation, policy execution, badges, MCP, plugin). | Performance of a contract with you or your organization. |
| Secure the Service (rate limiting, abuse detection, fraud prevention, audit logging). | Legitimate interests in keeping the Service available and trustworthy. |
| Operate, maintain, and improve the Service (debugging, performance tuning, aggregate usage analysis). | Legitimate interests in operating and improving the Service. |
| Respond to support, security, or privacy requests. | Performance of a contract; legitimate interests; legal obligation where applicable. |
| Comply with law and respond to lawful requests. | Legal obligation. |

## 5. Sharing

We share personal data with the sub-processors listed on our [sub-processors page](sub-processors.md), each engaged under a written agreement that limits their use of the data to providing services to us. We share data with law-enforcement or government bodies only when required by a binding legal request or to protect the rights, property, or safety of GitGrit, our users, or the public. We do not sell personal data and we do not use it for advertising or to train third-party AI models.

## 6. International transfers

The Service is hosted in the European Union (AWS region `eu-north-1`, Stockholm, Sweden). Some sub-processors are located in the United States or operate global edge networks. Where personal data is transferred outside the European Economic Area or the United Kingdom, we rely on the European Commission's Standard Contractual Clauses (and the UK Addendum where applicable) and apply supplementary technical measures — including encryption of access tokens at rest and TLS in transit — informed by a transfer-impact assessment. You may request a copy of the relevant transfer mechanism by emailing [privacy@gitgrit.dev](mailto:privacy@gitgrit.dev).

## 7. Retention

- **Account data.** Kept while the account is active. Deleted or anonymized within thirty (30) days of account closure, subject to the backup window in §8.
- **Encrypted access tokens.** Kept only while the connection exists; deleted when you remove the connection.
- **Repository data fetched for evaluation.** Cached only as long as needed to complete a policy run; not persisted in raw form.
- **Webhook deliveries.** Not retained as a separate record; the resulting policy execution record applies (see below).
- **Policy execution records.** Twelve (12) months, after which they are aggregated for trend analysis without identifying individuals.
- **Service logs.** Thirty (30) days.
- **Security audit logs.** Twelve (12) months for integrity and incident-investigation purposes.
- **Support correspondence.** Twenty-four (24) months from the last message in the thread.

## 8. Backups

Backups containing personal data are retained for up to ninety (90) days in encrypted form. Deletions of live data propagate to backups on the next backup-rotation cycle within that window.

## 9. Your rights

Subject to your jurisdiction's law, you have rights to: access your personal data; correct inaccurate data; have your data erased; restrict or object to processing based on legitimate interests; receive your data in a portable format; and withdraw consent where processing is based on consent. To exercise any of these rights, email [privacy@gitgrit.dev](mailto:privacy@gitgrit.dev). We will respond within thirty (30) days. If you are in the EU, EEA, UK, or Switzerland, you may also lodge a complaint with your supervisory authority.

## 10. Cookies

The Service sets only cookies that are strictly necessary to operate it. See our [cookies notice](cookies.md) for the full list and lifetimes.

## 11. Security

We apply technical and organizational measures appropriate to the risk, including: encryption of platform access tokens at rest with Fernet; TLS for data in transit; HMAC verification of incoming webhooks; gVisor-sandboxed execution of policy code; least-privilege role assignments; and security logging. Our threat model and disclosure process are documented in [SECURITY.md](https://github.com/kfirzvi-com/gitgrit/blob/main/SECURITY.md). No system is perfectly secure; we cannot guarantee that personal data will never be compromised.

## 12. Children

The Service is not directed at children under sixteen (16), and we do not knowingly collect personal data from them. If you believe we have inadvertently collected data from a child, contact [privacy@gitgrit.dev](mailto:privacy@gitgrit.dev) and we will delete it.

## 13. Automated decision-making

The Service evaluates repositories against policies you have enabled and produces a compliance score. These results are informational; we do not make decisions that produce legal or similarly significant effects on individuals based solely on automated processing.

## 14. AI integrations

The Service offers MCP and a Claude Code plugin so third-party large-language-model clients can read GitGrit data and propose policy edits. When you connect such a client, the prompts and the data it reads are transmitted to the model provider you have configured under that provider's terms and privacy policy. GitGrit itself does not send user data to any AI provider for training.

## 15. Changes to this notice

We may update this Privacy Policy from time to time. The "Effective" date at the top reflects the current version. We will announce material changes at least thirty (30) days before they take effect via the Service or by email to the address on file.
