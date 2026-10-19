# Buildathon project brief

## Problem

Creator-content workflows often mix source context, generated copy, factual
claims, approval state, and publishing intent in one unstructured step. That
makes missing context easy to guess, unsupported claims easy to repeat, and
approval boundaries difficult to audit.

## What this project implements

Mustafa Content OS is a local, profile-driven workflow foundation that:

1. Resolves a selected profile and its declared source files.
2. Applies deterministic readiness gates before drafting or public use.
3. Validates YAML/JSON against explicit JSON Schema contracts.
4. Tracks claim and evidence references without treating structure as proof.
5. Enforces assertion applicability for identity, positioning, repository, result,
   and attribution statements.
6. Authorizes CTA mechanics only from the selected profile configuration.
7. Requires explicit human approval before an approved/public handoff.
8. Preserves terminal failures and detects changed authoritative inputs.

The implementation is local Python code. It does not publish content, call an
Instagram API, or fabricate scheduling confirmations.

## Safety model

- Unknown values remain unresolved instead of being guessed.
- Public tests use synthetic fixture data only.
- Public readiness is stricter than private drafting readiness.
- Claim/evidence registry membership is not independent fact verification.
- Render, schedule, and publication integrations are intentionally unconfigured.
- The submission contains no real creator profiles, evidence, drafts, renders, or
  internal reports.

## Supported result

The clean-machine result is a deterministic local validation/test workflow. A
future user can copy `profiles/_template/` into their own private workspace and
supply authoritative data separately; that data is not part of this submission.
