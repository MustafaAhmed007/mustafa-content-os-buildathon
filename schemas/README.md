# MUSTAFA CONTENT OS Ω contracts

These files define the machine-facing contracts for the content operating system.
They are definitions only in Phase 0. No validator, registry, renderer adapter,
scheduler, analytics importer, or publishing integration is implemented yet.

The contracts are JSON Schema documents stored as `.schema.json` files. Profile
data can remain YAML or Markdown for human editing, provided its machine-critical
fields follow the corresponding contract.

## Authority model

| Domain | Phase 0 authoritative source | Notes |
|---|---|---|
| Active creator | `profiles/active.yaml` | Selects the profile used by profile-aware instructions. It remains `manthan` for compatibility. |
| Creator profile | The selected profile's `profile.yaml` and referenced files | A legacy profile may reference the original root files. |
| Identity | `identity.md` in a structured profile, or the legacy source declared by `profile.yaml` | No identity is inferred. |
| Business | `business.yaml` in a structured profile, or the legacy source declared by `profile.yaml` | Business facts are separate from offers. |
| Audience | `audience.yaml` in a structured profile, or the legacy source declared by `profile.yaml` | Audience facts are not claims until a later evidence phase. |
| Offers | `offers.yaml` in a structured profile, or the legacy source declared by `profile.yaml` | Prices and CTA policy belong here, not in generic command logic. |
| Voice | `voice.md` in a structured profile, or the legacy source declared by `profile.yaml` | System voice rules remain a separate policy layer. |
| Brand | `brand.yaml` in a structured profile, or the legacy source declared by `profile.yaml` | Colors, typography, and marks are creator-specific tokens. |
| Channels | `channels.yaml` in a structured profile, or the legacy source declared by `profile.yaml` | Handles, account IDs, and time zones belong here. |
| Strategy | `strategy.md` in a structured profile, or the legacy source declared by `profile.yaml` | Calendar and pillars are creator-specific. |
| Claims | A future claim record following `claim.schema.json` | No claim registry exists in this phase. |
| Evidence | A future evidence record following `evidence.schema.json` | No evidence registry or verification engine exists in this phase. |
| Content | A content item following `content-item.schema.json` | Existing Markdown files remain valid legacy content records. |
| Rendering | A future manifest following `render-manifest.schema.json` | The existing example app remains hard-coded and untouched. |
| Scheduling | A future record following `schedule.schema.json` | `/schedule` remains a documented handoff only. |
| Publication | A future record following `publication.schema.json` | No publishing integration exists yet. |

## Profile modes

`structured` profiles own their creator-specific files inside the profile
directory. `legacy-reference` profiles preserve the existing repository by
declaring which original files remain authoritative. This allows the profile
layer to be introduced without copying or silently changing Manthan's context.

The active profile is intentionally still `manthan`. Mustafa's profile is a
scaffold only and must not be activated until its `TODO_VERIFY` fields are
replaced with user-supplied facts.

## Boundary rules

- Generic instructions resolve `profiles/active.yaml` first.
- Creator-specific facts come from the resolved profile or its declared legacy sources.
- System policies describe behavior and must not supply creator identity, offers, metrics, or proof.
- References are study material and are never authoritative facts.
- A schema is not evidence. Claim and evidence contracts are reserved for a later phase.
