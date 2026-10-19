# Public demo script

Run this from the repository root after installing `requirements.lock` in the
Python 3.11.2 virtual environment.

## 1. Validate the synthetic claim registry

```bash
python -B scripts/validate_claim_registry.py \
  tests/fixtures/public/knowledge/claims.yaml
```

Expected result:

```text
VALID claim registry (structure and unique IDs only; not proof verification)
```

## 2. Validate the synthetic evidence registry

```bash
python -B scripts/validate_evidence_registry.py \
  tests/fixtures/public/knowledge/evidence.yaml \
  --claims tests/fixtures/public/knowledge/claims.yaml \
  --repository-root tests/fixtures/public
```

Expected result:

```text
VALID evidence registry (structure, artifact integrity, and claim references; not proof verification)
```

## 3. Validate one public content item

```bash
python -B scripts/validate_content.py \
  tests/fixtures/public/content/valid.yaml \
  --mode public \
  --format human \
  --claims tests/fixtures/public/knowledge/claims.yaml \
  --evidence tests/fixtures/public/knowledge/evidence.yaml \
  --repository-root tests/fixtures/public
```

Expected result begins with `PASS` and reports the synthetic claim/evidence
classification. The fixture is not creator content and must not be published.

## 4. Run the complete public suite

```bash
python -B -m unittest discover -s tests -p 'test_*.py'
```

The verified suite contains 242 tests. All profile, workflow, claim, evidence,
assertion, CTA, and terminal-state cases run against synthetic fixture data.
