# Verification record

Environment used for the local checks:

- Linux container, x86_64.
- CPython 3.11.2.
- Locked packages: PyYAML 6.0.2, attrs 24.2.0, jsonschema 4.23.0,
  jsonschema-specifications 2024.10.1, referencing 0.35.1, rpds-py 0.20.1.

## PASS

```bash
python3.11 -m venv .venv
python -m pip install --requirement requirements.lock
python -m pip check
python -m compileall -q scripts tests
python -B -m unittest discover -s tests -p 'test_*.py'
```

The complete public suite ran **242 tests** and finished `OK`.

The synthetic claim registry, evidence registry, and public content fixture
also passed their documented validator commands. A clean clone made from the
submission repository installed the lockfile, passed `pip check`, compiled the
source, and passed all 242 tests.

## BLOCKED BY HOST

Docker was installed locally and the daemon was started with a host-compatible
configuration. The Docker build reached the base-image layer download but the
container environment rejected layer ownership restoration:

```text
failed to register layer: ApplyLayer exit status 1
lchown /etc/gshadow: invalid argument
```

This is a host filesystem/container-runtime limitation, not an application
test failure. The image build and container command remain unverified here.

## Publication

The submission repository has no remote configured. No GitHub repository was
created, no push was performed, and no external submission ID was generated.
