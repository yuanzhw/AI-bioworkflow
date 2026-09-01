# Security Policy

AI-bioworkflow is currently an alpha engineering preview. Security fixes are
provided on a best-effort basis for the current `0.1.x` pre-release line and the
latest `main` branch. Older snapshots and unmaintained forks are not supported.

## Reporting a vulnerability

Do not disclose a suspected vulnerability in a public issue, pull request,
discussion, screenshot, or demo run.

Email the maintainer at `yuanzhw@vip.qq.com` with the subject
`[AI-bioworkflow security] <short summary>`. Include only the information needed
to reproduce and assess the issue:

- the affected release or commit SHA;
- the affected component and deployment mode;
- the expected impact and attack prerequisites;
- minimal reproduction steps or a proof of concept;
- suggested mitigations, if known;
- whether the issue has been disclosed elsewhere.

Do not send API keys, credentials, patient data, controlled-access biological
data, or unrelated private logs. Use synthetic or redacted inputs whenever
possible.

The maintainer aims to acknowledge a complete report within five business days
and provide an initial assessment within fourteen business days. These are
best-effort targets for a single-maintainer project, not guaranteed response
times. Please allow time for a fix and coordinated disclosure before publishing
details.

## Useful report scope

Security reports are especially useful when they concern:

- command-template or parameter injection;
- unintended file access or path traversal;
- unsafe handling of API input, stored run artifacts, or diagnostics;
- leakage of secrets or raw model/provider output;
- bypasses of Catalog, Reviewer patch policy, validation, or execution policy;
- unauthorized workflow execution or execution-backend boundary violations;
- dependency, container, or build-pipeline supply-chain risks;
- cross-site scripting, request forgery, or other Web/API vulnerabilities.

The public demo intentionally has no user accounts, multi-tenancy, or production
availability commitment. Reports that only restate these documented alpha
limitations may not be treated as vulnerabilities, but a concrete bypass,
credential exposure, unauthorized execution path, or material impact is in
scope.

## Coordinated disclosure

Confirmed vulnerabilities will be addressed according to severity and project
capacity. A fix may include a patch release, configuration guidance, credential
rotation, or temporary feature disablement. Credit will be offered when desired
and when disclosure is safe, but confidential or anonymous reporting is also
respected.

Only test repositories, systems, containers, and deployments that you own or
are explicitly authorized to assess.
