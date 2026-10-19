"""Read-only structural validation for the claim registry, not claim verification."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys

import yaml
from jsonschema import Draft202012Validator, FormatChecker, ValidationError, validators
from jsonschema.exceptions import SchemaError


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "knowledge/claims.yaml"
DEFAULT_SCHEMA = ROOT / "schemas/claim-registry.schema.json"


class UniqueSafeLoader(yaml.SafeLoader):
    """Reject duplicate/non-string keys before YAML can silently overwrite them."""


def unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in mapping:
            raise yaml.constructor.ConstructorError(
                "while reading a mapping",
                node.start_mark,
                f"non-string or duplicate key: {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping
)


def unique_json(pairs):
    mapping = {}
    for key, value in pairs:
        if key in mapping:
            raise ValueError(f"duplicate schema key: {key!r}")
        mapping[key] = value
    return mapping


def unique_by(validator, property_name, instance, schema):
    if not validator.is_type(instance, "array"):
        return
    seen = {}
    for index, record in enumerate(instance):
        if not isinstance(record, dict):
            continue
        value = record.get(property_name)
        if not isinstance(value, str):
            continue  # Required/type checks report malformed IDs separately.
        if value in seen:
            yield ValidationError(
                f"duplicate {property_name} {value!r} at records {seen[value]} and {index}"
            )
        else:
            seen[value] = index


RegistryValidator = validators.extend(Draft202012Validator, {"x-unique-by": unique_by})
FORMATS = FormatChecker()


@FORMATS.checks("date-time", raises=ValueError)
def timezone_datetime(value):
    # Use the standard library so date-time checks do not silently disappear
    # when jsonschema's optional format dependencies are absent.
    if not isinstance(value, str):
        return True  # The schema reports non-string types.
    if not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-](?:[01]\d|2[0-3]):[0-5]\d)",
        value,
    ):
        return False
    parsed = datetime.fromisoformat(value.upper().replace("Z", "+00:00"))
    return parsed.tzinfo is not None


def validate_registry(registry_path=DEFAULT_REGISTRY, schema_path=DEFAULT_SCHEMA):
    """Return structural errors; never mutate files or change claim permissions."""
    try:
        schema = json.loads(Path(schema_path).read_text(), object_pairs_hook=unique_json)
        Draft202012Validator.check_schema(schema)
        registry = yaml.load(Path(registry_path).read_text(), Loader=UniqueSafeLoader)
        validator = RegistryValidator(schema, format_checker=FORMATS)
        errors = sorted(
            validator.iter_errors(registry),
            key=lambda error: "/".join(str(part) for part in error.absolute_path),
        )
        return [
            f"{'/'.join(str(part) for part in error.absolute_path) or '$'}: {error.message}"
            for error in errors
        ]
    except (OSError, ValueError, yaml.YAMLError, SchemaError) as error:
        return [str(error)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry", nargs="?", type=Path, default=DEFAULT_REGISTRY)
    args = parser.parse_args()
    errors = validate_registry(args.registry)
    if errors:
        print("INVALID claim registry", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("VALID claim registry (structure and unique IDs only; not proof verification)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
