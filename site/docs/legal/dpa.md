---
title: Data Processing Agreement
description: The GDPR Article 28 terms under which GitGrit processes personal data on behalf of its customers.
---

# Data Processing Agreement

*Effective 2026-11-26.*

This Data Processing Agreement ("DPA") forms part of the [Terms of Service](terms.md) between you, the customer ("Customer"), and Kfir Zvi, self-employed, NIF Z5107624L, Calle Arquitectos Alamo y Ceballos 1, 26006 Logroño, La Rioja, Spain ("GitGrit"). It applies whenever GitGrit processes personal data on the Customer's behalf through the hosted service at [app.gitgrit.dev](https://app.gitgrit.dev) (the "Service"), and satisfies Article 28(3) of Regulation (EU) 2016/679 ("GDPR") and the UK GDPR. It does not apply to self-hosted GitGrit, where GitGrit processes nothing.

The Customer is the controller and GitGrit is the processor of the personal data described below. Personal data GitGrit processes for its own purposes (account sign-in, billing, security, website analytics) is covered by the [Privacy Policy](privacy.md), where GitGrit is the controller.

## 1. Details of the processing

| Item | Detail |
| --- | --- |
| Subject matter | Evaluating the Customer's connected repositories and uploaded artifacts against the standards the Customer enables, and showing the results. |
| Duration | For as long as the Customer uses the Service, plus the deletion period in section 9. |
| Nature and purpose | Retrieving repository data from GitHub or GitLab on request, running standards in sandboxed containers, storing execution records and scores, and showing them to the Customer's workspace members. |
| Categories of data subjects | People whose data appears in the Customer's repositories: commit authors, committers, reviewers, repository members, and anyone named in the repository contents. |
| Types of personal data | Names, usernames, email addresses, and avatar URLs from commit metadata and platform member lists, and any personal data inside files that the Customer's standards read. |
| Special categories | None intended. The Customer must not use the Service to process special-category data (GDPR Article 9) or data on criminal convictions. |

## 2. Instructions

GitGrit processes the personal data only on the Customer's documented instructions. The Terms, this DPA, and the Customer's configuration of the Service (connections, projects, and enabled standards) are those instructions. GitGrit will tell the Customer if it believes an instruction infringes data protection law, and is not obliged to follow it. If EU or Member State law requires other processing, GitGrit will tell the Customer before processing unless that law prohibits it.

## 3. Confidentiality

Everyone GitGrit authorises to process the personal data is bound by confidentiality.

## 4. Security

GitGrit applies the technical and organisational measures required by GDPR Article 32, including:

- platform access tokens encrypted at rest (Fernet);
- TLS for all data in transit;
- standard code run in gVisor-sandboxed containers isolated from other customers' data;
- HMAC verification of incoming webhooks;
- least-privilege access to production, with audit logging;
- encrypted backups kept for up to ninety (90) days;
- hosting in the European Union (AWS `eu-north-1`, Stockholm, Sweden).

## 5. Sub-processors

The Customer gives GitGrit general authorisation to engage the sub-processors listed on the [sub-processors page](sub-processors.md). GitGrit will update that page at least thirty (30) days before engaging a new sub-processor, and notify Customers who have asked for notice at the contact on file. The Customer may object on reasonable data-protection grounds within that period; if the parties cannot resolve the objection, the Customer may close its account. GitGrit imposes data protection obligations on each sub-processor equivalent to this DPA and remains responsible to the Customer for their performance.

## 6. International transfers

GitGrit hosts the Service in the EU. Where a sub-processor processes the personal data outside the EEA, GitGrit relies on an adequacy decision (including the EU–US Data Privacy Framework for certified recipients) or the European Commission's Standard Contractual Clauses, with the UK Addendum where applicable.

## 7. Assistance

Taking into account the nature of the processing, GitGrit helps the Customer:

- respond to data subjects exercising their rights. GitGrit forwards any request it receives directly to the Customer and does not answer it unless the Customer instructs it to;
- meet its obligations on security, breach notification, data protection impact assessments, and prior consultation (GDPR Articles 32 to 36).

## 8. Personal data breaches

GitGrit notifies the Customer without undue delay, and in any case within forty-eight (48) hours, after becoming aware of a personal data breach affecting the Customer's data. The notice describes the breach, the data and data subjects affected as far as known, likely consequences, and the measures taken or proposed, and is updated as more becomes known.

## 9. Deletion

When the Customer closes its account or removes a connection or project, GitGrit deletes the related personal data within thirty (30) days, and from backups within ninety (90) days, unless EU or Member State law requires it to keep the data. The Customer can export its results through the API before closing its account.

## 10. Audits

GitGrit makes available all information needed to demonstrate compliance with this DPA and GDPR Article 28, and allows for and contributes to audits, including inspections, by the Customer or an auditor it mandates. The Customer gives reasonable notice, and audits take place no more than once a year unless a supervisory authority requires otherwise or after a personal data breach.

## 11. Liability and precedence

Each party's liability under this DPA is subject to the limitations in the Terms, except where the GDPR does not allow them. If this DPA conflicts with the Terms on the processing of personal data, this DPA prevails.

## 12. Signed copy

This DPA applies without a signature when you accept the Terms. For a countersigned copy, email [kfir@praktical.dev](mailto:kfir@praktical.dev).
