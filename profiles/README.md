# Creator profiles

Creator-specific data is resolved through this directory. Generic operating
instructions must not assume a name, handle, offer, audience, metric, proof
source, calendar, or CTA keyword.

## Active profile

`active.yaml` selects the profile used by profile-aware instructions. It remains
set to `manthan` during Phase 1 so the current repository behavior is preserved.
The `mustafa` profile is intentionally incomplete and must not be activated yet.

## Profile modes

### Structured profile

A structured profile owns its creator data in its directory:

```text
profiles/<profile-id>/
├── profile.yaml
├── identity.md
├── audience.yaml
├── offers.yaml
├── voice.md
├── brand.yaml
├── channels.yaml
├── business.yaml
└── strategy.md
```

The six files in the requested profile surface are the minimum creator-facing
surface. `business.yaml`, `strategy.md`, and `profile.yaml` make the authority
boundaries and machine resolution explicit.

### Legacy-reference profile

The current Manthan material is represented by a small adapter at
`profiles/manthan/profile.yaml`. It points to the existing root context files
instead of copying them. Those original files remain authoritative in this
phase, which avoids two copies drifting apart.

## Authority rules

- Profile data is authoritative for creator-specific facts.
- The legacy adapter's declared source files are authoritative for the legacy profile.
- `systems/` contains reusable policy and format rules, not creator facts.
- `references/` contains study material, not authoritative claims.
- `schemas/` defines contracts only. It does not validate or verify data yet.
- `TODO_VERIFY` means the value is intentionally unknown and must not be treated as a fact.

## Adding a creator

1. Copy `profiles/_template/` to a new profile ID.
2. Replace placeholders only with facts supplied by that creator.
3. Complete the profile files and review their authority fields.
4. Do not change `active.yaml` until the profile is complete and approved.
