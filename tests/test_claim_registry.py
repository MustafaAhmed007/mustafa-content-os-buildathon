"""Contract and failure-path checks for the claim registry foundation only."""

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FIXTURE_ROOT = ROOT / "tests/fixtures/public"
SCRIPT = ROOT / "scripts/validate_claim_registry.py"
spec = importlib.util.spec_from_file_location("validate_claim_registry", SCRIPT)
validation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validation)


class ClaimRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = yaml.load(
            (PUBLIC_FIXTURE_ROOT / "knowledge/claims.yaml").read_text(),
            Loader=validation.UniqueSafeLoader,
        )

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.path = Path(self.temp_directory.name) / "claims.yaml"
        self.data = copy.deepcopy(self.registry)

    def write_registry(self):
        self.path.write_text(yaml.safe_dump(self.data, sort_keys=False, allow_unicode=True))
        return self.path

    def test_authoritative_registry_validates_and_empty_references_are_allowed(self):
        self.assertEqual(validation.validate_registry(PUBLIC_FIXTURE_ROOT / "knowledge/claims.yaml"), [])
        self.assertEqual(self.registry["profile"], "mustafa")
        for claim in self.data["claims"]:
            claim["evidence_refs"] = []
        self.assertEqual(validation.validate_registry(self.write_registry()), [])
        self.assertFalse(
            {"metric_claim", "result_claim", "testimonial_claim", "capability_claim"}
            & {c["claim_type"] for c in self.registry["claims"]}
        )

    def test_every_record_field_is_required(self):
        for field in self.registry["claims"][0]:
            with self.subTest(field=field):
                self.data = copy.deepcopy(self.registry)
                del self.data["claims"][0][field]
                self.assertTrue(validation.validate_registry(self.write_registry()))

    def test_invalid_enums_are_rejected(self):
        for field in ["claim_type", "status", "verification_status", "public_use"]:
            with self.subTest(field=field):
                self.data = copy.deepcopy(self.registry)
                self.data["claims"][0][field] = "unsupported"
                self.assertTrue(validation.validate_registry(self.write_registry()))

    def test_duplicate_ids_rejected_when_records_differ(self):
        duplicate = copy.deepcopy(self.data["claims"][0])
        duplicate["notes"].append("Different metadata must not conceal a duplicate ID.")
        self.data["claims"].append(duplicate)
        errors = validation.validate_registry(self.write_registry())
        self.assertTrue(any("duplicate claim_id" in e for e in errors), errors)

    def test_identical_duplicate_records_rejected(self):
        self.data["claims"].append(copy.deepcopy(self.data["claims"][0]))
        self.assertTrue(validation.validate_registry(self.write_registry()))

    def test_malformed_evidence_references_rejected(self):
        for refs in ["evidence-1", [1], [None], [{"id": "evidence-1"}], [""], [" "], ["evidence-1", "evidence-1"]]:
            with self.subTest(refs=refs):
                self.data["claims"][0]["evidence_refs"] = refs
                self.assertTrue(validation.validate_registry(self.write_registry()))

    def test_missing_scope_or_unknown_fields_rejected(self):
        del self.data["profile"]
        self.assertTrue(validation.validate_registry(self.write_registry()))
        self.data = copy.deepcopy(self.registry)
        self.data["claims"][0]["unsupported_field"] = True
        self.assertTrue(validation.validate_registry(self.write_registry()))

    def test_duplicate_yaml_keys_rejected(self):
        self.path.write_text("schema_version: '1.0'\nprofile: mustafa\nprofile: other\nclaims: []\n")
        errors = validation.validate_registry(self.path)
        self.assertTrue(any("duplicate key" in e for e in errors), errors)

    def test_unsafe_yaml_tags_rejected(self):
        self.path.write_text("!!python/object/apply:builtins.str [unsafe]\n")
        self.assertTrue(validation.validate_registry(self.path))

    def test_malformed_yaml_and_wrong_root_type_rejected(self):
        for text in ["claims: [", "[]\n", "null\n", ""]:
            with self.subTest(text=text):
                self.path.write_text(text)
                self.assertTrue(validation.validate_registry(self.path))

    def test_dates_checked_without_optional_format_dependencies(self):
        for field in ["created_at", "expires_at"]:
            for value in ["not-a-date", "2026-13-01T00:00:00Z", "2026-02-30T00:00:00Z", "2026-10-05T00:00:00", "2026-10-05T00:00:00+01:99"]:
                with self.subTest(field=field, value=value):
                    self.data = copy.deepcopy(self.registry)
                    self.data["claims"][0][field] = value
                    self.assertTrue(validation.validate_registry(self.write_registry()))

    def test_expiry_placeholder_does_not_authorize_evidence(self):
        self.data["claims"][0]["expires_at"] = "TODO_VERIFY"
        self.assertEqual(validation.validate_registry(self.write_registry()), [])
        self.data["claims"][0]["created_at"] = "TODO_VERIFY"
        self.assertTrue(validation.validate_registry(self.write_registry()))

    def test_duplicate_schema_keys_rejected(self):
        schema_path = Path(self.temp_directory.name) / "schema.json"
        schema_path.write_text('{"type":"object","type":"array"}')
        errors = validation.validate_registry(self.write_registry(), schema_path)
        self.assertTrue(any("duplicate schema key" in e for e in errors), errors)

    def test_invalid_schema_reported(self):
        schema_path = Path(self.temp_directory.name) / "schema.json"
        schema_path.write_text(json.dumps({"type": "not-a-json-schema-type"}))
        self.assertTrue(validation.validate_registry(self.write_registry(), schema_path))

    def test_cli_exit_codes_and_read_only_behavior(self):
        path = self.write_registry()
        original = path.read_bytes()
        valid = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), str(path)], capture_output=True, text=True
        )
        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertEqual(path.read_bytes(), original)
        self.data["claims"][0]["status"] = "unsupported"
        path = self.write_registry()
        original = path.read_bytes()
        invalid = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), str(path)], capture_output=True, text=True
        )
        self.assertEqual(invalid.returncode, 1)
        self.assertIn("INVALID", invalid.stderr)
        self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
