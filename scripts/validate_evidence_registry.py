"""Read-only evidence structure, artifact-integrity, and claim-reference checks."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

import yaml

if __package__:
    from .validate_claim_registry import (
        DEFAULT_REGISTRY as DEFAULT_CLAIMS,
        DEFAULT_SCHEMA as CLAIM_SCHEMA,
        ROOT,
        UniqueSafeLoader,
        unique_json,
        validate_registry,
    )
else:
    from validate_claim_registry import (
        DEFAULT_REGISTRY as DEFAULT_CLAIMS,
        DEFAULT_SCHEMA as CLAIM_SCHEMA,
        ROOT,
        UniqueSafeLoader,
        unique_json,
        validate_registry,
    )


DEFAULT_EVIDENCE = ROOT / "knowledge/evidence.yaml"
DEFAULT_SCHEMA = ROOT / "schemas/evidence-registry.schema.json"


def read_document(path):
    text = Path(path).read_text()
    if Path(path).suffix == ".json":
        return json.loads(text, object_pairs_hook=unique_json)
    return yaml.load(text, Loader=UniqueSafeLoader)


def resolve_pointer(document, pointer):
    value = document
    for part in pointer.split("/")[1:]:
        key = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict):
            value = value[key]
        elif isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", key):
            value = value[int(key)]
        else:
            raise ValueError(f"unresolvable selector: {pointer!r}")
    return value


def validate_evidence_registry(
    evidence_path=DEFAULT_EVIDENCE,
    claims_path=DEFAULT_CLAIMS,
    schema_path=DEFAULT_SCHEMA,
    repository_root=ROOT,
):
    """Return errors without changing evidence, claims, or publication permissions."""
    errors = [
        f"evidence: {error}"
        for error in validate_registry(evidence_path, schema_path)
    ]
    errors.extend(
        f"claims: {error}"
        for error in validate_registry(claims_path, CLAIM_SCHEMA)
    )
    if errors:
        return errors

    try:
        evidence = read_document(evidence_path)
        claims = read_document(claims_path)
        if evidence["profile"] != claims["profile"]:
            errors.append("evidence and claims have different profile scopes")

        evidence_ids = {record["evidence_id"] for record in evidence["evidence"]}
        for claim in claims["claims"]:
            for ref in claim["evidence_refs"]:
                if ref not in evidence_ids:
                    errors.append(f"claim {claim['claim_id']!r}: dangling evidence_ref {ref!r}")

        root = Path(repository_root).resolve()
        for record in evidence["evidence"]:
            locator = record["locator"]
            try:
                path = (root / locator["path"]).resolve()
                path.relative_to(root)  # Reject symlinks escaping the repository.
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                if digest != locator["sha256"]:
                    errors.append(f"evidence {record['evidence_id']!r}: artifact SHA-256 mismatch")
                    continue
                resolve_pointer(read_document(path), locator["selector"])
            except (OSError, ValueError, KeyError, IndexError, yaml.YAMLError) as error:
                errors.append(f"evidence {record['evidence_id']!r}: invalid locator: {error}")
    except (OSError, ValueError, yaml.YAMLError) as error:
        errors.append(str(error))
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", nargs="?", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--claims", type=Path, default=DEFAULT_CLAIMS)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    args = parser.parse_args()
    errors = validate_evidence_registry(args.evidence, args.claims, repository_root=args.repository_root)
    if errors:
        print("INVALID evidence registry", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("VALID evidence registry (structure, artifact integrity, and claim references; not proof verification)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
