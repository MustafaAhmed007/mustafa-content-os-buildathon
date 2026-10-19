"""Fixture-based content/reference/permission tests; never edit creator data."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

from scripts import validate_content as validation


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FIXTURE_ROOT = ROOT / "tests/fixtures/public"
SCRIPT = ROOT / "scripts/validate_content.py"
FIXTURES = PUBLIC_FIXTURE_ROOT / "content"


class ContentValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_content = validation.read_document(FIXTURES / "valid.yaml")
        cls.base_claims = validation.read_document(PUBLIC_FIXTURE_ROOT / "knowledge/claims.yaml")
        cls.base_evidence = validation.read_document(PUBLIC_FIXTURE_ROOT / "knowledge/evidence.yaml")

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.root = Path(self.temp_directory.name)
        self.claims_path = self.root / "claims.yaml"
        self.evidence_path = self.root / "evidence.yaml"
        self.reset_data()
        for name in {record["locator"]["path"] for record in self.evidence["evidence"]}:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((PUBLIC_FIXTURE_ROOT / name).read_bytes())

    def reset_data(self):
        self.content = copy.deepcopy(self.base_content)
        self.claims = copy.deepcopy(self.base_claims)
        self.evidence = copy.deepcopy(self.base_evidence)

    def write_registries(self):
        self.claims_path.write_text(yaml.safe_dump(self.claims, sort_keys=False, allow_unicode=True))
        self.evidence_path.write_text(yaml.safe_dump(self.evidence, sort_keys=False, allow_unicode=True))

    def validate(self, mode=None):
        self.write_registries()
        return validation.validate_content(
            self.content, mode=mode, claims_path=self.claims_path,
            evidence_path=self.evidence_path, repository_root=self.root,
        )

    def assert_failure(self, result, code):
        self.assertFalse(result["valid"], result)
        self.assertEqual(result["result"], "FAIL")
        self.assertIn(code, {error["code"] for error in result["errors"]}, result)

    def test_valid_public_content_item(self):
        result = self.validate("public")
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["result"], "PASS")
        self.assertTrue(result["public_facing"])
        self.assertEqual([c["claim_id"] for c in result["claims"]], ["mustafa-public-name"])
        self.assertEqual([e["evidence_id"] for e in result["evidence"]], ["evidence-mustafa-public-name"])

    def test_unknown_claim_at_item_and_slide_level(self):
        for location in ["item", "slide"]:
            with self.subTest(location=location):
                self.reset_data()
                if location == "item":
                    self.content["claims"] = ["fixture-missing-claim"]
                else:
                    self.content["slides"] = [{"number": 1, "role": "body", "claim_refs": ["fixture-missing-claim"]}]
                self.assert_failure(self.validate(), "UNKNOWN_CLAIM")

    def test_unknown_direct_evidence_at_item_and_slide_level(self):
        for location in ["item", "slide"]:
            with self.subTest(location=location):
                self.reset_data()
                if location == "item":
                    self.content["evidence_refs"] = ["fixture-missing-evidence"]
                else:
                    self.content["slides"] = [{"number": 1, "role": "body", "evidence_refs": ["fixture-missing-evidence"]}]
                self.assert_failure(self.validate(), "UNKNOWN_EVIDENCE")

    def test_dangling_claim_evidence_reference(self):
        self.claims["claims"][0]["evidence_refs"] = ["fixture-missing-evidence"]
        result = self.validate()
        self.assert_failure(result, "UNKNOWN_EVIDENCE")
        self.assertTrue(any(e["path"].startswith("/claim_registry/") for e in result["errors"]))

    def test_removing_referenced_evidence_record_fails(self):
        self.evidence["evidence"] = self.evidence["evidence"][1:]
        self.assert_failure(self.validate(), "UNKNOWN_EVIDENCE")

    def test_restricted_claim_public_use_flags(self):
        for permission in ["private", "internal_only", "needs_approval", "TODO_VERIFY"]:
            with self.subTest(permission=permission):
                self.reset_data()
                self.claims["claims"][0]["public_use"] = permission
                self.assert_failure(self.validate("public"), "RESTRICTED_CLAIM")

    def test_restricted_evidence_public_use_flags(self):
        for permission in ["private", "internal_only", "needs_approval", "TODO_VERIFY"]:
            with self.subTest(permission=permission):
                self.reset_data()
                self.evidence["evidence"][0]["public_use"] = permission
                self.assert_failure(self.validate("public"), "RESTRICTED_EVIDENCE")

    def test_direct_evidence_permissions_are_enforced_without_claims(self):
        self.content["claims"] = []
        self.content["slides"] = [{"number": 1, "role": "body", "evidence_refs": ["evidence-mustafa-public-name"]}]
        self.evidence["evidence"][0]["public_use"] = "internal_only"
        self.assert_failure(self.validate("public"), "RESTRICTED_EVIDENCE")

    def test_profile_scope_for_content_and_both_registries(self):
        for location in ["content", "claims", "evidence"]:
            with self.subTest(location=location):
                self.reset_data()
                getattr(self, location)["profile"] = "manthan"
                self.assert_failure(self.validate(), "PROFILE_MISMATCH")

    def test_legacy_profile_id_is_supported_and_alias_conflicts_fail(self):
        self.content["profile_id"] = self.content.pop("profile")
        self.assertTrue(self.validate()["valid"])
        self.content["profile"] = "mustafa"
        self.assertTrue(self.validate()["valid"])
        self.content["profile_id"] = "manthan"
        self.assert_failure(self.validate(), "PROFILE_MISMATCH")

    def test_missing_required_metadata(self):
        for field in ["schema_version", "content_id", "profile", "platform", "content_type", "status"]:
            with self.subTest(field=field):
                self.reset_data()
                del self.content[field]
                self.assert_failure(self.validate(), "MISSING_REQUIRED_FIELD")

    def test_blank_or_wrong_type_metadata(self):
        for field in ["content_id", "profile", "platform", "content_type"]:
            for value in ["", "   ", None, [], 7]:
                with self.subTest(field=field, value=value):
                    self.reset_data()
                    self.content[field] = value
                    self.assertFalse(self.validate()["valid"])

    def test_optional_content_fields_do_not_become_required(self):
        self.content = {
            "schema_version": "1.0", "content_id": "legacy-minimal",
            "profile_id": "mustafa", "platform": "portfolio",
            "content_type": "text", "status": "draft",
        }
        result = self.validate()
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["claims"], [])

    def test_duplicate_references_within_each_array(self):
        for field in ["claims", "evidence_refs", "slide_claim_refs", "slide_evidence_refs", "registry_evidence_refs"]:
            with self.subTest(field=field):
                self.reset_data()
                claim_id = "mustafa-public-name"
                evidence_id = "evidence-mustafa-public-name"
                if field == "claims":
                    self.content[field] = [claim_id, claim_id]
                elif field == "evidence_refs":
                    self.content[field] = [evidence_id, evidence_id]
                elif field.startswith("slide_"):
                    key = field.removeprefix("slide_")
                    ref = claim_id if key == "claim_refs" else evidence_id
                    self.content["slides"] = [{"number": 1, "role": "body", key: [ref, ref]}]
                else:
                    self.claims["claims"][0]["evidence_refs"] = [evidence_id, evidence_id]
                self.assert_failure(self.validate(), "DUPLICATE_REFERENCE")

    def test_same_reference_in_distinct_locations_is_valid(self):
        self.content["evidence_refs"] = ["evidence-mustafa-public-name"]
        self.content["slides"] = [
            {"number": i, "role": "body", "claim_refs": ["mustafa-public-name"], "evidence_refs": ["evidence-mustafa-public-name"]}
            for i in [1, 2]
        ]
        result = self.validate("public")
        self.assertTrue(result["valid"], result)
        self.assertEqual(len(result["claims"]), 1)
        self.assertEqual(len(result["evidence"]), 1)

    def test_duplicate_registry_ids_with_identical_or_different_records(self):
        for registry_name, collection in [("claims", "claims"), ("evidence", "evidence")]:
            for different in [False, True]:
                with self.subTest(registry=registry_name, different=different):
                    self.reset_data()
                    records = getattr(self, registry_name)[collection]
                    duplicate = copy.deepcopy(records[0])
                    if different:
                        duplicate["notes"].append("Fixture-only changed metadata.")
                    records.append(duplicate)
                    self.assert_failure(self.validate(), "DUPLICATE_ID")

    def test_duplicate_slide_numbers_fail(self):
        self.content["slides"] = [{"number": 1, "role": "cover"}, {"number": 1, "role": "body"}]
        self.assert_failure(self.validate(), "DUPLICATE_ID")

    def test_malformed_content_references(self):
        for value in ["not-an-array", [None], [1], [{"claim_id": "mustafa-public-name"}], [""], ["bad id"]]:
            with self.subTest(value=value):
                self.reset_data()
                self.content["claims"] = value
                self.assert_failure(self.validate(), "MALFORMED_REFERENCE")
        self.reset_data()
        self.content["slides"] = [{"number": 1, "role": "body", "claim_refs": ["bad id"]}]
        self.assert_failure(self.validate(), "MALFORMED_REFERENCE")

    def test_malformed_claim_owned_evidence_references(self):
        for value in ["not-an-array", [None], ["bad id"], ["UPPER_CASE_ID"]]:
            with self.subTest(value=value):
                self.reset_data()
                self.claims["claims"][0]["evidence_refs"] = value
                self.assert_failure(self.validate(), "MALFORMED_REFERENCE")

    def test_self_reported_and_other_classifications_are_preserved(self):
        for classification in ["self_reported", "source_verified", "first_party_verified", "third_party_verified"]:
            with self.subTest(classification=classification):
                self.reset_data()
                self.claims["claims"][0]["verification_status"] = classification
                self.evidence["evidence"][0]["verification_status"] = classification
                result = self.validate("public")
                self.assertTrue(result["valid"], result)
                self.assertEqual(result["claims"][0]["verification_status"], classification)
                self.assertEqual(result["evidence"][0]["verification_status"], classification)

    def test_valid_internal_draft_and_review_with_restricted_records(self):
        self.claims["claims"][0]["public_use"] = "private"
        self.evidence["evidence"][0]["public_use"] = "internal_only"
        for mode in ["draft", "review"]:
            with self.subTest(mode=mode):
                result = self.validate(mode)
                self.assertTrue(result["valid"], result)
                self.assertFalse(result["public_facing"])
                self.assertEqual(result["claims"][0]["public_use"], "private")
                self.assertEqual(result["evidence"][0]["public_use"], "internal_only")

    def test_explicit_approved_and_public_modes_enforce_permissions(self):
        self.claims["claims"][0]["public_use"] = "private"
        for mode in ["approved", "public"]:
            with self.subTest(mode=mode):
                self.assert_failure(self.validate(mode), "RESTRICTED_CLAIM")

    def test_public_facing_status_cannot_be_downgraded_by_mode(self):
        self.evidence["evidence"][0]["public_use"] = "needs_approval"
        for status in ["approved", "public", "scheduled", "published"]:
            for mode in [None, "draft", "review"]:
                with self.subTest(status=status, mode=mode):
                    self.content["status"] = status
                    result = self.validate(mode)
                    self.assertTrue(result["public_facing"])
                    self.assert_failure(result, "RESTRICTED_EVIDENCE")

    def test_existing_and_new_content_statuses_are_supported(self):
        for status in ["idea", "draft", "review", "approved", "public", "scheduled", "published", "killed", "archived"]:
            with self.subTest(status=status):
                self.content["status"] = status
                result = self.validate()
                self.assertTrue(result["valid"], result)
                self.assertEqual(result["public_facing"], status in validation.PUBLIC_STATUSES)

    def test_claim_lifecycle_and_unverified_or_expired_records(self):
        for status in ["candidate", "expired", "restricted", "TODO_VERIFY"]:
            with self.subTest(status=status):
                self.reset_data()
                self.claims["claims"][0]["status"] = status
                self.assert_failure(self.validate("public"), "RESTRICTED_CLAIM")
                self.assertTrue(self.validate("draft")["valid"])
        for registry_name, collection, code in [
            ("claims", "claims", "RESTRICTED_CLAIM"),
            ("evidence", "evidence", "RESTRICTED_EVIDENCE"),
        ]:
            for classification in ["unverified", "expired"]:
                with self.subTest(registry=registry_name, classification=classification):
                    self.reset_data()
                    getattr(self, registry_name)[collection][0]["verification_status"] = classification
                    self.assert_failure(self.validate("public"), code)
                    self.assertTrue(self.validate("draft")["valid"])

    def test_only_referenced_records_are_permission_gated(self):
        self.claims["claims"][1]["public_use"] = "private"
        self.evidence["evidence"][1]["public_use"] = "private"
        self.assertTrue(self.validate("public")["valid"])

    def test_bare_metric_reference_does_not_establish_assertion_applicability(self):
        # This fixture is not a real creator metric or evidence of a measured value.
        self.claims["claims"][0]["claim_id"] = "fixture-metric"
        self.claims["claims"][0]["claim_type"] = "metric_claim"
        self.claims["claims"][0]["claim"] = "Fixture-only metric declaration."
        self.content["claims"] = ["fixture-metric"]
        result = self.validate("public")
        self.assert_failure(result, "UNCLASSIFIED_ASSERTION")
        self.assertEqual(result["claims"][0]["claim_type"], "metric_claim")
        self.content["claims"] = ["fixture-missing-metric"]
        self.assert_failure(self.validate("public"), "UNKNOWN_CLAIM")

    def test_unstructured_numbers_are_not_automatically_interpreted(self):
        self.content["claims"] = []
        self.content["hook"] = "Fixture text with 123 and 4.5%."
        self.content["caption"] = "Arbitrary fixture prose with $999 and 2x."
        result = self.validate("public")
        self.assert_failure(result, "UNCLASSIFIED_ASSERTION")
        self.assertEqual(result["claims"], [])
        self.assertTrue(any("not extracted" in text for text in result["limitations"]))
        self.assertTrue(self.validate("draft")["valid"])

    def test_empty_evidence_references_and_unresolved_expiry_are_reported(self):
        self.claims["claims"][0]["evidence_refs"] = []
        result = self.validate("public")
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["evidence"], [])
        self.assertEqual(result["claims"][0]["expires_at"], "TODO_VERIFY")
        self.assertTrue(any("Expiry policy" in text for text in result["limitations"]))

    def test_artifact_integrity_failure_is_propagated(self):
        artifact = self.root / self.evidence["evidence"][0]["locator"]["path"]
        artifact.write_bytes(artifact.read_bytes() + b"\n# fixture corruption\n")
        result = self.validate()
        self.assert_failure(result, "INVALID_EVIDENCE_REGISTRY")
        self.assertTrue(any("SHA-256 mismatch" in e["message"] for e in result["errors"]))

    def test_registry_structural_errors_fail(self):
        self.claims["claims"][0]["claim_type"] = "not-a-type"
        self.assert_failure(self.validate(), "INVALID_CLAIM_REGISTRY")
        self.reset_data()
        self.evidence["evidence"][0]["public_use"] = "not-a-permission"
        self.assert_failure(self.validate(), "INVALID_EVIDENCE_REGISTRY")

    def test_invalid_mode_schema_and_unknown_content_fields(self):
        self.assert_failure(self.validate("invalid"), "INVALID_VALIDATION_MODE")
        self.content["extra_field"] = True
        self.assert_failure(self.validate(), "INVALID_CONTENT_SCHEMA")
        self.write_registries()
        schema_path = self.root / "schema.json"
        schema_path.write_text(json.dumps({"type": "invalid"}))
        result = validation.validate_content(self.content, schema_path=schema_path)
        self.assert_failure(result, "INVALID_CONTENT_SCHEMA")

    def test_content_file_parsing_rejects_duplicate_keys_unsafe_yaml_and_wrong_roots(self):
        path = self.root / "content.yaml"
        for text in [
            "profile: mustafa\nprofile: manthan\n",
            "!!python/object/apply:builtins.str [unsafe]\n",
            "claims: [", "[]\n", "null\n",
        ]:
            with self.subTest(text=text):
                path.write_text(text)
                self.assert_failure(validation.validate_content(path), "INVALID_CONTENT_SCHEMA")
        path = self.root / "content.json"
        path.write_text('{"profile":"mustafa","profile":"manthan"}')
        self.assert_failure(validation.validate_content(path), "INVALID_CONTENT_SCHEMA")

    def test_invalid_registry_documents_fail_cleanly(self):
        for registry_name in ["claims", "evidence"]:
            with self.subTest(registry=registry_name):
                self.write_registries()
                path = getattr(self, registry_name + "_path")
                path.write_text("profile: mustafa\nprofile: other\n")
                result = validation.validate_content(self.content, claims_path=self.claims_path, evidence_path=self.evidence_path)
                self.assert_failure(result, "INVALID_CLAIM_REGISTRY" if registry_name == "claims" else "INVALID_EVIDENCE_REGISTRY")

    def test_cli_human_json_exit_codes_and_read_only_behavior(self):
        self.write_registries()
        content_path = self.root / "content.json"
        for valid in [True, False]:
            self.content["claims"] = ["mustafa-public-name" if valid else "fixture-missing-claim"]
            content_path.write_text(json.dumps(self.content))
            paths = [content_path, self.claims_path, self.evidence_path, PUBLIC_FIXTURE_ROOT / "repository/profiles/active.yaml"]
            before = [path.read_bytes() for path in paths]
            for output in ["human", "json"]:
                with self.subTest(valid=valid, output=output):
                    process = subprocess.run(
                        [sys.executable, "-B", str(SCRIPT), str(content_path), "--mode", "public",
                         "--format", output, "--claims", str(self.claims_path), "--evidence", str(self.evidence_path),
                         "--repository-root", str(self.root)],
                        capture_output=True, text=True,
                    )
                    self.assertEqual(process.returncode, 0 if valid else 1, process.stderr)
                    if output == "json":
                        result = json.loads(process.stdout)
                        self.assertEqual(result["valid"], valid)
                        if valid:
                            self.assertEqual(result["claims"][0]["verification_status"], "self_reported")
                    else:
                        self.assertTrue(process.stdout.startswith("PASS" if valid else "FAIL"))
                    if not valid:
                        self.assertIn("UNKNOWN_CLAIM", process.stdout)
            self.assertEqual([path.read_bytes() for path in paths], before)

    def test_missing_content_file_is_machine_readable_failure(self):
        process = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), str(self.root / "missing.yaml"), "--format", "json"],
            capture_output=True, text=True,
        )
        self.assertEqual(process.returncode, 1, process.stderr)
        self.assert_failure(json.loads(process.stdout), "INVALID_CONTENT_SCHEMA")

    def test_validation_is_repeatable_and_does_not_mutate_input(self):
        before = copy.deepcopy(self.content)
        first = self.validate("public")
        second = self.validate("public")
        self.assertEqual(first, second)
        self.assertEqual(self.content, before)


if __name__ == "__main__":
    unittest.main()
