"""Structured assertion applicability; all result evidence is fixture-only."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_content_validator as content_fixtures
import test_carousel_integration as carousel_fixtures
from scripts import validate_content as validation
from scripts import carousel_workflow as workflow


class ClaimApplicabilityTests(unittest.TestCase):
    setUpClass = classmethod(content_fixtures.ContentValidatorTests.setUpClass.__func__)
    setUp = content_fixtures.ContentValidatorTests.setUp
    reset_data = content_fixtures.ContentValidatorTests.reset_data
    write_registries = content_fixtures.ContentValidatorTests.write_registries
    validate = content_fixtures.ContentValidatorTests.validate
    assert_failure = content_fixtures.ContentValidatorTests.assert_failure

    def assertion(self, kind="identity", claim_id="mustafa-public-name", text=None):
        claim = next((item for item in self.claims["claims"] if item["claim_id"] == claim_id), None)
        text = text if text is not None else claim["claim"]
        self.content.update(hook="", caption=text, cta="", slides=[], claims=[claim_id] if claim_id else [])
        item = {"assertion_id": "fixture-assertion", "target": "/caption", "text": text,
                "assertion_type": kind, "subject": claim["subject"] if claim else "Fixture-only automation",
                "claim_refs": [claim_id] if claim_id else []}
        self.content["assertions"] = [item]
        return item

    def metric_fixture(self):
        """Synthetic test records, never Mustafa facts or evidence upgrades."""
        quantity = {"metric": "time_saved", "value": 5, "unit": "hours", "period": "fixture-week"}
        claim = copy.deepcopy(self.claims["claims"][0])
        claim.update(claim_id="fixture-time-result", claim_type="result_claim", subject="Fixture-only automation",
                     claim="Fixture-only automation saves 5 hours in the fixture week.",
                     source="fixture-metric.json#/measurement", source_type="fixture_only",
                     verification_status="first_party_verified", evidence_refs=["fixture-time-evidence"],
                     applicability={"assertion_types": ["quantitative_result", "operational_performance"], "quantitative": quantity})
        evidence = copy.deepcopy(self.evidence["evidence"][0])
        evidence.update(evidence_id="fixture-time-evidence", subject=claim["subject"], evidence_type="metric",
                        verification_status="first_party_verified", source="fixture-metric.json", source_type="fixture_only")
        payload = {"measurement": {"subject": claim["subject"], "quantitative": quantity, "statement": claim["claim"]}}
        artifact = self.root / "fixture-metric.json"
        artifact.write_text(json.dumps(payload))
        evidence["locator"] = {"path": artifact.name, "selector": "/measurement", "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}
        self.claims["claims"].append(claim)
        self.evidence["evidence"].append(evidence)
        assertion = self.assertion("quantitative_result", claim["claim_id"])
        assertion["quantitative"] = copy.deepcopy(quantity)
        return claim, evidence, assertion

    def test_valid_identity_claim_supports_identity_assertion(self):
        self.assertion()
        result = self.validate("public")
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["assertions"][0]["result"], "PASS")

    def test_positioning_claim_supports_only_self_description(self):
        assertion = self.assertion("positioning", "mustafa-primary-positioning")
        assertion["basis"] = "self_description"
        self.assertTrue(self.validate("public")["valid"])
        assertion["basis"] = "independently_verified"
        self.assert_failure(self.validate("public"), "ASSERTION_SCOPE_MISMATCH")

    def test_repository_observation_supports_historical_existence(self):
        assertion = self.assertion("repository_existence", "mustafa-adaptiverag-repository-observation")
        assertion["temporal_scope"] = "historical"
        self.assertTrue(self.validate("public")["valid"])
        assertion["temporal_scope"] = "current"
        self.assert_failure(self.validate("public"), "ASSERTION_SCOPE_MISMATCH")

    def test_identity_claim_cannot_support_quantitative_result(self):
        assertion = self.assertion("quantitative_result", text="This automation saves businesses 5 hours every week.")
        assertion["quantitative"] = {"metric": "time_saved", "value": 5, "unit": "hours", "period": "weekly"}
        self.assert_failure(self.validate("public"), "CLAIM_NOT_APPLICABLE")

    def test_identity_claim_cannot_support_time_saving(self):
        self.assertion("operational_performance", text="This automation saves businesses time.")
        self.assert_failure(self.validate("public"), "CLAIM_NOT_APPLICABLE")

    def test_identity_claim_cannot_support_percentage_reduction(self):
        assertion = self.assertion("quantitative_result", text="Our deployments reduced costs by 65%.")
        assertion["quantitative"] = {"metric": "cost_reduction", "value": 65, "unit": "%", "period": "fixture-period"}
        self.assert_failure(self.validate("public"), "CLAIM_NOT_APPLICABLE")

    def test_positioning_cannot_support_business_performance(self):
        self.assertion("operational_performance", "mustafa-positioning-statement", "My deployments improve business performance.")
        self.assert_failure(self.validate("public"), "CLAIM_NOT_APPLICABLE")

    def test_misclassified_identity_cannot_hide_an_outcome(self):
        self.assertion("identity", text="This automation saves businesses 5 hours every week.")
        self.assert_failure(self.validate("public"), "ASSERTION_TEXT_UNSUPPORTED")

    def test_unverified_evidence_cannot_be_upgraded_by_content(self):
        _, evidence, assertion = self.metric_fixture()
        evidence["verification_status"] = "unverified"
        assertion["basis"] = "independently_verified"
        self.assert_failure(self.validate("public"), "INSUFFICIENT_ASSERTION_EVIDENCE")
        assertion["verification_status"] = "third_party_verified"
        self.assert_failure(self.validate("public"), "INVALID_CONTENT_SCHEMA")

    def test_self_reported_classification_remains_self_reported(self):
        self.assertion()
        result = self.validate("public")
        self.assertEqual(result["claims"][0]["verification_status"], "self_reported")
        self.assertEqual(result["evidence"][0]["verification_status"], "self_reported")

    def test_quantitative_assertion_without_supporting_claim_fails(self):
        self.metric_fixture()
        self.content["assertions"][0]["claim_refs"] = []
        self.assert_failure(self.validate("public"), "MISSING_ASSERTION_CLAIM")

    def test_verified_quantitative_fixture_passes_without_registry_mutation(self):
        self.metric_fixture()
        before = copy.deepcopy((self.content, self.claims, self.evidence))
        result = self.validate("public")
        self.assertTrue(result["valid"], result)
        self.assertTrue(result["continue"])
        self.assertEqual((self.content, self.claims, self.evidence), before)

    def test_every_attached_claim_must_support_the_assertion(self):
        self.metric_fixture()
        self.content["assertions"][0]["claim_refs"].append("mustafa-public-name")
        self.assert_failure(self.validate("public"), "CLAIM_NOT_APPLICABLE")

    def test_subject_value_unit_period_and_metric_must_match(self):
        _, _, assertion = self.metric_fixture()
        original = copy.deepcopy(assertion)
        for field, value in [("value", 65), ("unit", "%"), ("period", "different-period"), ("metric", "latency")]:
            with self.subTest(field=field):
                assertion["quantitative"] = copy.deepcopy(original["quantitative"])
                assertion["quantitative"][field] = value
                self.assert_failure(self.validate("public"), "ASSERTION_SCOPE_MISMATCH")
        assertion["quantitative"] = original["quantitative"]
        assertion["subject"] = "Different customer"
        self.assert_failure(self.validate("public"), "ASSERTION_SCOPE_MISMATCH")

    def test_metric_capture_must_support_the_declared_measurement(self):
        _, evidence, _ = self.metric_fixture()
        artifact = self.root / "fixture-metric.json"
        payload = json.loads(artifact.read_text())
        payload["measurement"]["quantitative"]["value"] = 1
        artifact.write_text(json.dumps(payload))
        evidence["locator"]["sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
        self.assert_failure(self.validate("public"), "INSUFFICIENT_ASSERTION_EVIDENCE")

    def test_self_reported_source_verified_or_visual_proof_cannot_prove_results(self):
        claim, evidence, _ = self.metric_fixture()
        for classification in ["self_reported", "source_verified", "unverified"]:
            with self.subTest(classification=classification):
                claim["verification_status"] = classification
                evidence["verification_status"] = classification
                self.assert_failure(self.validate("public"), "INSUFFICIENT_ASSERTION_EVIDENCE")
        claim["verification_status"] = evidence["verification_status"] = "first_party_verified"
        evidence["evidence_type"] = "screenshot"
        self.assert_failure(self.validate("public"), "INSUFFICIENT_ASSERTION_EVIDENCE")

    def test_unrelated_direct_evidence_cannot_replace_claim_owned_support(self):
        claim, _, assertion = self.metric_fixture()
        claim["evidence_refs"] = []
        assertion["evidence_refs"] = ["fixture-time-evidence"]
        self.assert_failure(self.validate("public"), "INSUFFICIENT_ASSERTION_EVIDENCE")

    def test_unknown_assertion_type_fails_public_factual_content(self):
        self.assertion("unknown")
        self.assert_failure(self.validate("public"), "UNCLASSIFIED_ASSERTION")

    def test_unknown_claim_reference_still_fails(self):
        self.assertion()
        self.content["assertions"][0]["claim_refs"] = ["fixture-unknown-claim"]
        self.assert_failure(self.validate("public"), "UNKNOWN_CLAIM")

    def test_duplicate_and_invalid_assertion_references_still_fail(self):
        assertion = self.assertion()
        for refs, code in [(["mustafa-public-name", "mustafa-public-name"], "DUPLICATE_REFERENCE"), (["bad id"], "MALFORMED_REFERENCE"), ([None], "MALFORMED_REFERENCE")]:
            with self.subTest(refs=refs):
                assertion["claim_refs"] = refs
                self.assert_failure(self.validate("public"), code)

    def test_assertions_are_bound_to_actual_copy_and_valid_targets(self):
        assertion = self.assertion()
        self.content["caption"] = "Unsupported rewritten copy."
        self.assert_failure(self.validate("public"), "ASSERTION_TEXT_MISMATCH")
        assertion["target"] = "/claims/0"
        self.assert_failure(self.validate("public"), "INVALID_ASSERTION_TARGET")

    def test_public_copy_without_safe_classification_fails_closed(self):
        self.content["caption"] = "This automation saves businesses 5 hours every week."
        self.assert_failure(self.validate("public"), "UNCLASSIFIED_ASSERTION")
        self.assertFalse(self.validate("public")["continue"])

    def test_safe_existing_identity_fixture_remains_valid(self):
        result = self.validate("public")
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["applicability_coverage"], "structured assertions and exact supported literals")

    def test_spans_allow_explicitly_classified_mixed_copy(self):
        assertion = self.assertion()
        identity_text = assertion["text"]
        explanation = "Fixture-only procedural note."
        self.content["caption"] = identity_text + "\n" + explanation
        assertion["span"] = {"start": 0, "end": len(identity_text)}
        self.content["assertions"].append({"assertion_id": "fixture-note", "target": "/caption", "text": explanation,
                                           "span": {"start": len(identity_text) + 1, "end": len(self.content["caption"])},
                                           "assertion_type": "non_factual", "claim_refs": []})
        self.assertTrue(self.validate("public")["valid"])
        self.content["assertions"].pop()
        self.assert_failure(self.validate("public"), "UNCLASSIFIED_ASSERTION")

    def test_content_permissions_cannot_downgrade_public_mode(self):
        assertion = self.assertion()
        assertion["public_usage"] = "private"
        self.assert_failure(self.validate("public"), "RESTRICTED_ASSERTION")

    def test_externally_attributed_assertion_cannot_use_identity(self):
        assertion = self.assertion("externally_attributed", text="A customer says this saves hours.")
        assertion["attribution"] = "Fixture customer"
        self.assert_failure(self.validate("public"), "CLAIM_NOT_APPLICABLE")

    def test_result_scope_must_be_explicit_even_for_metric_claim_type(self):
        claim, _, _ = self.metric_fixture()
        del claim["applicability"]
        self.assert_failure(self.validate("public"), "CLAIM_NOT_APPLICABLE")

    def test_claim_type_cannot_be_widened_by_applicability_metadata(self):
        assertion = self.assertion("quantitative_result", text="This automation saves businesses 5 hours every week.")
        quantity = {"metric": "time_saved", "value": 5, "unit": "hours", "period": "weekly"}
        assertion["quantitative"] = quantity
        self.claims["claims"][0]["applicability"] = {"assertion_types": ["quantitative_result"], "quantitative": quantity}
        self.assert_failure(self.validate("public"), "CLAIM_NOT_APPLICABLE")

    def test_nonfinite_or_unresolved_measurement_scope_fails(self):
        claim, _, assertion = self.metric_fixture()
        for field, value in [("value", float("nan")), ("value", float("inf")), ("unit", "TODO_VERIFY"), ("period", "TODO_VERIFY")]:
            with self.subTest(field=field, value=value):
                quantity = {"metric": "time_saved", "value": 5, "unit": "hours", "period": "fixture-week"}
                quantity[field] = value
                claim["applicability"]["quantitative"] = copy.deepcopy(quantity)
                assertion["quantitative"] = quantity
                self.assert_failure(self.validate("public"), "ASSERTION_SCOPE_MISMATCH")

    def test_duplicate_assertion_ids_fail(self):
        assertion = self.assertion()
        self.content["assertions"].append(copy.deepcopy(assertion))
        self.assert_failure(self.validate("public"), "DUPLICATE_ID")

    def test_slide_reference_does_not_authorize_undeclared_time_savings(self):
        self.content["slides"] = [{"number": 1, "role": "body", "body": "This saves businesses 5 hours weekly.", "claim_refs": ["mustafa-public-name"]}]
        self.assert_failure(self.validate("public"), "UNCLASSIFIED_ASSERTION")

    def test_proof_signal_and_visual_only_classifications_are_not_promoted(self):
        _, evidence, _ = self.metric_fixture()
        for classification in ["proof_signal", "visual_only"]:
            with self.subTest(classification=classification):
                evidence["verification_status"] = classification
                self.assert_failure(self.validate("public"), "INVALID_EVIDENCE_REGISTRY")

    def test_externally_attributed_verified_fixture_requires_matching_attribution(self):
        claim, evidence, assertion = self.metric_fixture()
        statement = "Fixture customer says the fixture is useful."
        attribution = "Fixture customer"
        claim.update(claim_type="testimonial_claim", claim=statement,
                     applicability={"assertion_types": ["externally_attributed"], "attribution": attribution})
        evidence.update(evidence_type="testimonial", verification_status="third_party_verified")
        assertion.update(assertion_type="externally_attributed", text=statement, attribution=attribution)
        assertion.pop("quantitative")
        self.content["caption"] = statement
        artifact = self.root / "fixture-metric.json"
        artifact.write_text(json.dumps({"measurement": {"subject": claim["subject"], "statement": statement, "attribution": attribution}}))
        evidence["locator"]["sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
        self.assertTrue(self.validate("public")["valid"])
        assertion["attribution"] = "Another customer"
        self.assert_failure(self.validate("public"), "ASSERTION_SCOPE_MISMATCH")

    def test_applicability_cli_returns_nonzero_and_identifies_assertion(self):
        assertion = self.assertion("operational_performance", text="This automation saves businesses time.")
        self.write_registries()
        path = self.root / "content.json"
        path.write_text(json.dumps(self.content))
        process = subprocess.run([sys.executable, "-B", str(content_fixtures.SCRIPT), str(path), "--mode", "public", "--format", "json", "--claims", str(self.claims_path), "--evidence", str(self.evidence_path), "--repository-root", str(self.root)], capture_output=True, text=True)
        self.assertEqual(process.returncode, 1, process.stderr)
        result = json.loads(process.stdout)
        self.assert_failure(result, "CLAIM_NOT_APPLICABLE")
        self.assertIn(assertion["assertion_id"], json.dumps(result["errors"]))
        self.assertIn("mustafa-public-name", json.dumps(result["errors"]))


class ApplicabilityWorkflowTests(unittest.TestCase):
    setUp = carousel_fixtures.CarouselIntegrationTests.setUp
    write_yaml = carousel_fixtures.CarouselIntegrationTests.write_yaml
    write_frontmatter = carousel_fixtures.CarouselIntegrationTests.write_frontmatter
    content = carousel_fixtures.CarouselIntegrationTests.content
    checkpoint = carousel_fixtures.CarouselIntegrationTests.checkpoint
    finalize = carousel_fixtures.CarouselIntegrationTests.finalize
    complete_mustafa_fixture = carousel_fixtures.CarouselIntegrationTests.complete_mustafa_fixture

    def test_applicability_failure_prevents_export_and_is_terminal(self):
        self.complete_mustafa_fixture()
        path = self.content("mustafa")
        checkpoint = self.checkpoint(path)
        source = validation.read_document(path)
        source["caption"] = "This automation saves businesses 5 hours every week."
        source["assertions"] = [{"assertion_id": "unsupported-hours", "target": "/caption", "text": source["caption"],
                                  "assertion_type": "quantitative_result", "subject": "Example Creator", "claim_refs": ["mustafa-public-name"],
                                  "quantitative": {"metric": "time_saved", "value": 5, "unit": "hours", "period": "weekly"}}]
        self.write_yaml(path, source)
        with patch.object(workflow, "markdown") as export:
            first = self.finalize(path, checkpoint, "public")
        self.assertFalse(first["continue"])
        self.assertEqual(first["result"], "FAIL")
        self.assertIn("CLAIM_NOT_APPLICABLE", {error["code"] for error in first["errors"]})
        export.assert_not_called()
        self.assertFalse(path.with_suffix(".md").exists())
        self.assertEqual(validation.read_document(path.with_suffix(".validation-failure.json")), first)
        source["caption"] = "Example Creator"
        source.pop("assertions")
        self.write_yaml(path, source)
        self.assertEqual(self.finalize(path, checkpoint, "public"), first)

    def test_legacy_manthan_behavior_keeps_explicit_coverage_limit(self):
        path = self.content("manthan")
        result = self.finalize(path, self.checkpoint(path), "approved")
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["validation"]["applicability_coverage"], "legacy reference compatibility; undeclared prose is not applicability-checked")


if __name__ == "__main__":
    unittest.main()
