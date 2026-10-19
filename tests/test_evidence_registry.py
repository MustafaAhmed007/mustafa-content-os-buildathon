"""Evidence contract, artifact integrity, and cross-registry failure-path tests."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

from scripts import validate_evidence_registry as validation


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FIXTURE_ROOT = ROOT / "tests/fixtures/public"
SCRIPT = ROOT / "scripts/validate_evidence_registry.py"


class EvidenceRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = validation.read_document(PUBLIC_FIXTURE_ROOT / "knowledge/evidence.yaml")
        cls.claim_registry = validation.read_document(PUBLIC_FIXTURE_ROOT / "knowledge/claims.yaml")

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.root = Path(self.temp_directory.name)
        self.path = self.root / "evidence.yaml"
        self.claims_path = self.root / "claims.yaml"
        self.data = copy.deepcopy(self.registry)
        self.claims = copy.deepcopy(self.claim_registry)
        for record in self.data["evidence"]:
            source = PUBLIC_FIXTURE_ROOT / record["locator"]["path"]
            target = self.root / record["locator"]["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())

    def write_registries(self):
        self.path.write_text(yaml.safe_dump(self.data, sort_keys=False, allow_unicode=True))
        self.claims_path.write_text(yaml.safe_dump(self.claims, sort_keys=False, allow_unicode=True))

    def errors(self):
        self.write_registries()
        return validation.validate_evidence_registry(
            self.path, self.claims_path, repository_root=self.root
        )

    def test_registry_artifacts_and_links_validate(self):
        self.assertEqual(
            validation.validate_evidence_registry(
                PUBLIC_FIXTURE_ROOT / "knowledge/evidence.yaml",
                PUBLIC_FIXTURE_ROOT / "knowledge/claims.yaml",
                repository_root=PUBLIC_FIXTURE_ROOT,
            ),
            [],
        )
        self.assertEqual(self.registry["profile"], "mustafa")
        self.assertEqual(self.errors(), [])

    def test_every_record_field_is_required(self):
        for field in self.registry["evidence"][0]:
            with self.subTest(field=field):
                self.data = copy.deepcopy(self.registry)
                del self.data["evidence"][0][field]
                self.assertTrue(self.errors())

    def test_invalid_enums_are_rejected(self):
        for field in ["evidence_type", "verification_status", "public_use"]:
            with self.subTest(field=field):
                self.data = copy.deepcopy(self.registry)
                self.data["evidence"][0][field] = "unsupported"
                self.assertTrue(self.errors())

    def test_duplicate_evidence_ids_with_different_metadata_rejected(self):
        duplicate = copy.deepcopy(self.data["evidence"][0])
        duplicate["notes"].append("Different metadata must not conceal a duplicate ID.")
        self.data["evidence"].append(duplicate)
        errors = self.errors()
        self.assertTrue(any("duplicate evidence_id" in e for e in errors), errors)

    def test_identical_duplicate_records_rejected(self):
        self.data["evidence"].append(copy.deepcopy(self.data["evidence"][0]))
        self.assertTrue(self.errors())

    def test_blank_required_values_rejected(self):
        for field in ["evidence_id", "source", "source_type", "subject", "description"]:
            with self.subTest(field=field):
                self.data = copy.deepcopy(self.registry)
                self.data["evidence"][0][field] = "   "
                self.assertTrue(self.errors())

    def test_unknown_fields_rejected(self):
        self.data["evidence"][0]["unknown_field"] = True
        self.assertTrue(self.errors())
        self.data = copy.deepcopy(self.registry)
        self.data["unknown_field"] = True
        self.assertTrue(self.errors())
        self.data = copy.deepcopy(self.registry)
        self.data["evidence"][0]["locator"]["unknown_field"] = True
        self.assertTrue(self.errors())

    def test_malformed_locators_rejected(self):
        locators = ["", "https://example.com/", [], {}, {"path": ""}]
        for locator in locators:
            with self.subTest(locator=locator):
                self.data = copy.deepcopy(self.registry)
                self.data["evidence"][0]["locator"] = locator
                self.assertTrue(self.errors())
        for field, value in [
            ("path", "../outside.yaml"),
            ("path", "/absolute.yaml"),
            ("selector", ""),
            ("selector", "not-a-pointer"),
            ("selector", "/invalid~2escape"),
            ("sha256", "not-a-hash"),
        ]:
            with self.subTest(field=field, value=value):
                self.data = copy.deepcopy(self.registry)
                self.data["evidence"][0]["locator"][field] = value
                self.assertTrue(self.errors())

    def test_missing_artifact_and_unresolvable_selector_rejected(self):
        self.data["evidence"][0]["locator"]["path"] = "missing.yaml"
        self.assertTrue(self.errors())
        self.data = copy.deepcopy(self.registry)
        self.data["evidence"][0]["locator"]["selector"] = "/missing"
        self.assertTrue(self.errors())

    def test_changed_artifact_checksum_rejected(self):
        artifact = self.root / self.data["evidence"][0]["locator"]["path"]
        artifact.write_bytes(artifact.read_bytes() + b"\n# changed artifact\n")
        errors = self.errors()
        self.assertTrue(any("SHA-256 mismatch" in e for e in errors), errors)

    def test_artifact_symlink_outside_repository_rejected(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        external = Path(outside.name) / "external.yaml"
        original = self.root / self.data["evidence"][0]["locator"]["path"]
        external.write_bytes(original.read_bytes())
        original.unlink()
        original.symlink_to(external)
        errors = self.errors()
        self.assertTrue(any("invalid locator" in e for e in errors), errors)

    def test_dangling_claim_evidence_reference_rejected(self):
        self.claims["claims"][0]["evidence_refs"] = ["evidence-missing"]
        errors = self.errors()
        self.assertTrue(any("dangling evidence_ref" in e for e in errors), errors)

    def test_empty_claim_evidence_refs_remain_allowed(self):
        for claim in self.claims["claims"]:
            claim["evidence_refs"] = []
        self.assertEqual(self.errors(), [])

    def test_cross_profile_reference_set_rejected(self):
        self.data["profile"] = "other-profile"
        errors = self.errors()
        self.assertTrue(any("different profile scopes" in e for e in errors), errors)

    def test_malformed_claim_registry_rejected(self):
        self.claims["claims"][0]["evidence_refs"] = "not-an-array"
        self.assertTrue(self.errors())

    def test_dates_and_unresolved_expiry_policy(self):
        for field in ["captured_at", "expires_at"]:
            for value in ["not-a-date", "2026-02-30T00:00:00Z", "2026-10-05T00:00:00"]:
                with self.subTest(field=field, value=value):
                    self.data = copy.deepcopy(self.registry)
                    self.data["evidence"][0][field] = value
                    self.assertTrue(self.errors())
        self.data = copy.deepcopy(self.registry)
        self.data["evidence"][0]["expires_at"] = "TODO_VERIFY"
        self.assertEqual(self.errors(), [])

    def test_duplicate_keys_and_unsafe_or_malformed_yaml_rejected(self):
        self.write_registries()
        for text in [
            "schema_version: '1.0'\nprofile: mustafa\nprofile: other\nevidence: []\n",
            "!!python/object/apply:builtins.str [unsafe]\n",
            "evidence: [",
            "null\n",
        ]:
            with self.subTest(text=text):
                self.path.write_text(text)
                self.assertTrue(validation.validate_evidence_registry(self.path, self.claims_path))

    def test_captured_document_duplicate_keys_rejected(self):
        artifact = self.root / self.data["evidence"][0]["locator"]["path"]
        artifact.write_text("identity: {}\nidentity: {}\n")
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        for record in self.data["evidence"]:
            if record["locator"]["path"] == self.data["evidence"][0]["locator"]["path"]:
                record["locator"]["sha256"] = digest
        errors = self.errors()
        self.assertTrue(any("duplicate key" in e for e in errors), errors)

    def test_json_pointer_escaping_and_array_indexes(self):
        value = {"a/b": {"~key": ["observed"]}}
        self.assertEqual(validation.resolve_pointer(value, "/a~1b/~0key/0"), "observed")
        for pointer in ["/a~1b/~0key/-1", "/a~1b/~0key/01"]:
            with self.subTest(pointer=pointer):
                with self.assertRaises(ValueError):
                    validation.resolve_pointer(value, pointer)

    def test_invalid_schema_and_duplicate_schema_keys_rejected(self):
        self.write_registries()
        schema_path = self.root / "schema.json"
        for text in ['{"type":"object","type":"array"}', json.dumps({"type": "invalid"})]:
            with self.subTest(text=text):
                schema_path.write_text(text)
                self.assertTrue(validation.validate_evidence_registry(self.path, self.claims_path, schema_path))

    def test_cli_exit_codes_and_read_only_behavior(self):
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), str(PUBLIC_FIXTURE_ROOT / "knowledge/evidence.yaml"),
             "--claims", str(PUBLIC_FIXTURE_ROOT / "knowledge/claims.yaml"),
             "--repository-root", str(PUBLIC_FIXTURE_ROOT)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.claims["claims"][0]["evidence_refs"] = ["evidence-missing"]
        self.write_registries()
        before = (self.path.read_bytes(), self.claims_path.read_bytes())
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), str(self.path), "--claims", str(self.claims_path),
             "--repository-root", str(self.root)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("dangling evidence_ref", result.stderr)
        self.assertEqual(before, (self.path.read_bytes(), self.claims_path.read_bytes()))


if __name__ == "__main__":
    unittest.main()
