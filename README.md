# Mustafa Content OS Ω

Profile-driven content workflow foundations for deterministic validation,
explicit approval boundaries, and reproducible local checks.

This buildathon workspace is a privacy-safe submission copy. It contains the
workflow code, schemas, system contracts, templates, and source-level test
modules. Active profiles, claim and evidence registries, real content drafts,
protected date-specific artifacts, renders, and internal reports are
intentionally not included. Tests use only clearly labeled synthetic fixtures
under `tests/fixtures/public/`.

## Scope

The Python layer provides:

- YAML and JSON loading with duplicate-key protection.
- JSON Schema validation for content and workflow contracts.
- Deterministic claim, evidence, content, readiness, and approval helpers.
- Read-only validation commands and standard-library unit-test modules.

## Requirements

- Linux.
- CPython **3.11.2**, pinned in `.python-version`.
- `venv` and `pip` for local setup.
- Docker is optional and is only needed for the container path.

The Python code uses the standard library plus the exact packages in
`requirements.lock`:

- `PyYAML==6.0.2`
- `jsonschema==4.23.0`

The lockfile also pins jsonschema's runtime dependencies. The existing
`scripts/requirements-claims.txt` remains as the original compatible version
range; use `requirements.lock` for reproducible setup in this workspace.

## Linux setup

From the repository root:

```bash
python3.11 --version
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install --requirement requirements.lock
```

The version check must report `Python 3.11.2`. If that interpreter is not
available on the machine, install CPython 3.11.2 with the host's normal version
manager before creating the virtual environment.

No environment variables are required by the Python workflow, so this project
does not need an `.env.example` file.

## Build

The reproducible container build installs only the locked Python dependencies
and copies the privacy-safe source tree:

```bash
docker build --tag mustafa-content-os:local .
```

No application server or publishing service is started by the image.

## Run

Run the default container command:

```bash
docker run --rm mustafa-content-os:local
```

The image runs the complete public unit-test suite against the synthetic
fixtures included in the image. For local execution, activate the virtual
environment and run the same command from the repository root.

## Test

The reliable public test command for this workspace is:

```bash
python -B -m unittest discover -s tests -p 'test_*.py'
```

This runs the complete included suite against synthetic profile, registry,
evidence, content, and workflow fixtures. It does not read or recreate any
private creator data. For a faster syntax-only check, use:

```bash
python -m compileall -q scripts tests
```

## Repository layout

| Path | Purpose |
|---|---|
| `.python-version` | Exact CPython version pin |
| `requirements.lock` | Exact direct and transitive Python dependency versions |
| `Dockerfile` | Reproducible Python validation image |
| `.dockerignore` | Excludes credentials, generated output, and private-content paths from Docker context |
| `scripts/` | Validation and workflow helpers |
| `schemas/` | JSON Schema contracts |
| `systems/` | Reusable workflow and design policies |
| `profiles/_template/` | Creator-agnostic profile scaffold |
| `tests/` | Contract and workflow test modules |
| `tests/fixtures/public/` | Synthetic, fixture-only data used by the public test suite |
| `docs/buildathon-project.md` | Project scope and safety model |
| `docs/architecture.md` | Component and trust-boundary overview |
| `docs/demo-script.md` | Verified public demonstration commands |
| `docs/verification.md` | Actual verification results and host limitations |

## Safety boundaries

- Validation is local and read-only unless a command explicitly creates an
  artifact in its documented output location.
- Missing creator data remains missing; it is not inferred or replaced.
- Public tests use synthetic identities, claims, evidence, profiles, and content
  only. Fixture labels do not assert real people, projects, results, or offers.
- No credentials, private evidence, real drafts, protected artifacts, or
  temporary renders belong in this workspace.
- Human review remains required before any publication or scheduling handoff.

The original `LICENSE` file is preserved unchanged.
