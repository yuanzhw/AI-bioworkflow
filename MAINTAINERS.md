# Maintainers and Project Governance

AI-bioworkflow is an Apache-2.0 open-source project in alpha. This document
records operational maintainership and decision-making; it does not replace the
license or grant ownership of contributor work.

## Current maintainers

| Maintainer | GitHub | Role | Scope |
| --- | --- | --- | --- |
| Yuanzhw | [@yuanzhw](https://github.com/yuanzhw) | Owner and lead maintainer | Repository-wide architecture, Catalog admission, releases, infrastructure, and security response |

Operational review ownership is also recorded in
[`.github/CODEOWNERS`](./.github/CODEOWNERS).

## Responsibilities

Maintainers are responsible for:

- preserving the Recipe Tool Plan, Catalog, Workflow IR, deterministic Renderer,
  Checker, and execution-backend boundaries;
- reviewing issues and pull requests fairly and in a reasonable time;
- keeping tests, documentation, releases, and security guidance accurate;
- admitting tools, recipes, containers, and execution-verification evidence;
- protecting repository credentials and release infrastructure;
- enforcing the [Code of Conduct](./CODE_OF_CONDUCT.md) consistently.

## Decisions

Routine changes are decided through pull request review. Significant changes to
Workflow IR, public APIs, dependencies, Catalog policy, execution, security, or
project direction should begin with a public issue and a written proposal.

The project prefers documented technical consensus. When consensus cannot be
reached, the lead maintainer makes the final decision based on project scope,
architecture invariants, evidence, maintenance cost, and user impact. Decisions
may be revisited when new evidence becomes available.

Security-sensitive details may be handled privately until coordinated
disclosure is safe.

## Becoming a maintainer

Maintainer access may be offered after a sustained record of constructive
contributions, reliable review, sound judgment around bioinformatics and
compiler boundaries, and compliance with the Code of Conduct. Candidates must
use two-factor authentication and accept the repository's security and release
practices.

There is no automatic contribution-count threshold. Maintainer access is based
on demonstrated trust and an ongoing need for shared ownership.

## Inactivity or removal

A maintainer may step down at any time. Access may be reduced after prolonged
inactivity, loss of two-factor authentication, repeated policy violations, or
conduct that puts users, contributors, or release integrity at risk. Whenever
practical, changes in maintainership will be documented in this file.
