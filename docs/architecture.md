# Architecture

```text
                    local idea / structured content
                                  |
                                  v
                    profile + source resolution
                                  |
                                  v
       systems/ policies  --->  readiness gates  <---  schemas/
                                  |
                    +-------------+-------------+
                    |                           |
                    v                           v
          private draft boundary       public/approval boundary
                    |                           |
                    +-------------+-------------+
                                  v
                 claim/evidence applicability checks
                                  |
                                  v
                     CTA authorization boundary
                                  |
                                  v
                  deterministic validation + terminal state
                                  |
                                  v
                       human-reviewed handoff only
```

## Main components

| Component | Responsibility |
|---|---|
| `systems/` | Reusable workflow, format, voice, and rubric policies |
| `schemas/` | Machine-readable contracts for profiles, content, claims, evidence, approvals, and handoffs |
| `scripts/carousel_workflow.py` | Profile resolution, readiness, strategy checkpoints, finalization, and terminal artifact state |
| `scripts/validate_content.py` | Content schema, scope, claim/evidence, assertion, and public-use validation |
| `scripts/validate_claim_registry.py` | Safe YAML/JSON loading, schema validation, unique IDs, and date checks |
| `scripts/validate_evidence_registry.py` | Evidence linkage, local artifact integrity, selector resolution, and containment checks |
| `tests/fixtures/public/` | Synthetic, fixture-only repository/profile/content data for reproducible tests |
| `Dockerfile` | Locked Python environment running the complete public test suite |

## Trust boundaries

The validator checks declared structure, references, permissions, and artifact
integrity. It does not independently verify identity, authorship, project
quality, metrics, testimonials, or publication outcomes. Human approval remains
outside the automated validator and is required before any publishing handoff.
