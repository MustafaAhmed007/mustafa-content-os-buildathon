"""Deterministic CTA authorization using isolated synthetic profile configuration."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_carousel_integration as fixtures
from scripts import carousel_workflow as workflow
from scripts import validate_content as validation
from scripts.validate_claim_registry import RegistryValidator


class CTAAuthorizationTests(unittest.TestCase):
    write_yaml = fixtures.CarouselIntegrationTests.write_yaml
    write_frontmatter = fixtures.CarouselIntegrationTests.write_frontmatter
    content = fixtures.CarouselIntegrationTests.content
    checkpoint = fixtures.CarouselIntegrationTests.checkpoint
    finalize = fixtures.CarouselIntegrationTests.finalize
    complete_mustafa_fixture = fixtures.CarouselIntegrationTests.complete_mustafa_fixture

    def setUp(self):
        fixtures.CarouselIntegrationTests.setUp(self)
        self.complete_mustafa_fixture()
        self.path = self.content("mustafa")
        self.source = validation.read_document(self.path)

    def authorize(self, mode="public"):
        return validation.authorize_cta(self.source, mode=mode, repository_root=self.root)

    def change(self, name, mutate):
        path = self.root / "profiles/mustafa" / name
        data = validation.read_document(path)
        mutate(data)
        self.write_yaml(path, data)

    def assert_rejected(self, report, component):
        self.assertFalse(report["valid"], report)
        self.assertFalse(report["continue"])
        self.assertFalse(report["authorized"])
        self.assertEqual(report["result"], "FAIL")
        self.assertTrue(any(row["component"] == component and row["status"] == "FAIL" for row in report["checks"]), report)
        self.assertIn("CTA_UNAUTHORIZED", {error["code"] for error in report["errors"]})

    def test_authorized_cta_passes(self):
        report = self.authorize()
        self.assertTrue(report["valid"], report)
        self.assertTrue(report["authorized"])

    def test_different_creative_wording_preserves_authorized_mechanics(self):
        self.source["cta"] = "Want the fixture guide? Comment FIXTURE and I send it over."
        self.assertTrue(self.authorize()["authorized"])
        self.source["cta"] = "Comment FIXTURE for the same guide, delivered privately."
        self.assertTrue(self.authorize()["authorized"])

    def test_invented_keyword_fails(self):
        self.source["cta_mechanics"]["keyword"] = "INVENTED"
        self.assert_rejected(self.authorize(), "keyword")

    def test_invented_offer_fails(self):
        self.source["cta_mechanics"]["offer_id"] = "invented-offer"
        self.assert_rejected(self.authorize(), "offer_id")

    def test_invented_destination_fails(self):
        self.source["cta_mechanics"]["destination"] = "https://example.test/invented"
        self.assert_rejected(self.authorize(), "destination")

    def test_invented_delivery_asset_fails(self):
        self.source["cta_mechanics"]["delivery_asset"] = "Invented deliverable"
        self.assert_rejected(self.authorize(), "delivery_asset")

    def test_invented_conversion_path_fails(self):
        self.source["cta_mechanics"]["conversion_path"] = "invented-payment-to-email"
        self.assert_rejected(self.authorize(), "conversion_path")

    def test_invented_cta_type_fails(self):
        self.source["cta_mechanics"]["cta_type"] = "invented_mechanic"
        self.assert_rejected(self.authorize(), "cta_type")

    def test_unauthorized_offer_permission_fails(self):
        self.change("offers.yaml", lambda data: data["offers"][0].update(public_use="needs_approval"))
        self.assert_rejected(self.authorize(), "offer_permission")

    def test_unresolved_configuration_never_authorizes_components(self):
        fields = {"primary_mechanic": "cta_type", "keyword": "keyword", "offer_selection": "offer_id", "destination_url": "destination", "delivery_asset": "delivery_asset", "conversion_path": "conversion_path"}
        original = validation.read_document(self.root / "profiles/mustafa/offers.yaml")
        for field, component in fields.items():
            with self.subTest(field=field):
                data = copy.deepcopy(original)
                data["cta_policy"][field] = "TODO_VERIFY"
                self.write_yaml(self.root / "profiles/mustafa/offers.yaml", data)
                self.assert_rejected(self.authorize(), component)

    def test_missing_conversion_path_is_not_inferred_from_primary_mechanic(self):
        self.change("offers.yaml", lambda data: data["cta_policy"].pop("conversion_path"))
        self.assert_rejected(self.authorize(), "conversion_path")

    def test_disabled_or_unavailable_offer_fails(self):
        for status in ["disabled", "unavailable", "inactive", "TODO_VERIFY"]:
            with self.subTest(status=status):
                self.change("offers.yaml", lambda data: data["offers"][0].update(status=status))
                self.assert_rejected(self.authorize(), "offer_status")

    def test_false_or_truthy_nonboolean_publishable_fails(self):
        for value in [False, None, "true", 1]:
            with self.subTest(value=value):
                self.change("offers.yaml", lambda data: data["offers"][0].update(publishable=value))
                self.assert_rejected(self.authorize(), "offer_publishable")

    def test_disabled_cta_policy_fails(self):
        self.change("offers.yaml", lambda data: data["cta_policy"].update(enabled=False))
        self.assert_rejected(self.authorize(), "policy_enabled")

    def test_wrong_channel_fails_without_fallback(self):
        self.source["platform"] = "linkedin"
        self.assert_rejected(self.authorize(), "channel")

    def test_wrong_account_fails(self):
        self.source["cta_mechanics"]["account"] = "@invented_account"
        self.assert_rejected(self.authorize(), "account")

    def test_unauthorized_channel_account_fails(self):
        self.change("channels.yaml", lambda data: data["channels"][0].update(publishable=False, public_use="needs_approval"))
        self.assert_rejected(self.authorize(), "channel_publishable")

    def test_claims_and_evidence_cannot_authorize_invented_mechanics(self):
        self.source["claims"] = ["mustafa-public-name", "mustafa-primary-positioning"]
        self.source["evidence_refs"] = ["evidence-mustafa-public-name"]
        self.source["cta_mechanics"]["destination"] = "https://example.test/invented"
        self.assert_rejected(self.authorize(), "destination")

    def omit_cta(self):
        self.source["cta"] = ""
        self.source.pop("cta_mechanics", None)
        self.source.pop("keyword", None)
        self.source.pop("offer_id", None)
        self.source["slides"][-1]["body"] = ""
        self.source["slides"][-1]["headline"] = ""

    def test_private_body_draft_can_omit_cta_when_policy_allows(self):
        self.omit_cta()
        self.change("offers.yaml", lambda data: data["cta_policy"].update(keyword="TODO_VERIFY"))
        report = self.authorize("draft")
        self.assertTrue(report["valid"], report)
        self.assertFalse(report["authorized"])
        self.assertTrue(report["omitted"])

    def test_private_omission_respects_explicit_policy_denial(self):
        self.omit_cta()
        for value in [False, None, "true", 1, "TODO_VERIFY"]:
            with self.subTest(value=value):
                self.change("offers.yaml", lambda data: data["cta_policy"].update(allow_private_draft_without_cta=value))
                self.assert_rejected(self.authorize("draft"), "private_omission")

    def test_public_carousel_cannot_omit_cta_authorization(self):
        self.omit_cta()
        self.assert_rejected(self.authorize(), "cta_mechanics")

    def test_missing_cta_classification_fails(self):
        del self.source["cta_mechanics"]["cta_type"]
        self.assert_rejected(self.authorize(), "cta_type")

    def test_missing_null_empty_and_model_generated_are_not_authorization(self):
        for value in [None, "", "TODO_VERIFY", "unresolved", "unknown", "inferred", "model-generated", "TBC", True, 1]:
            with self.subTest(value=value):
                self.source["cta_mechanics"]["keyword"] = value
                self.change("offers.yaml", lambda data: data["cta_policy"].update(keyword=value))
                self.assert_rejected(self.authorize(), "keyword")

    def test_generated_authorized_flag_cannot_grant_permission(self):
        self.source["cta_mechanics"]["authorized"] = True
        self.source["cta_mechanics"]["destination"] = "https://example.test/invented"
        self.assert_rejected(self.authorize(), "destination")

    def test_duplicate_offer_or_channel_is_ambiguous_and_rejected(self):
        self.change("offers.yaml", lambda data: data["offers"].append(copy.deepcopy(data["offers"][0])))
        self.assert_rejected(self.authorize(), "offer_selection")
        self.change("channels.yaml", lambda data: data["channels"].append(copy.deepcopy(data["channels"][0])))
        self.assert_rejected(self.authorize(), "channel")

    def test_wrong_profile_source_is_not_authorization(self):
        self.change("offers.yaml", lambda data: data.update(profile_id="another-creator"))
        self.assert_rejected(self.authorize(), "offers_scope")

    def test_report_is_deterministic_machine_readable_and_read_only(self):
        paths = [self.root / "profiles/mustafa" / name for name in ["offers.yaml", "channels.yaml", "profile.yaml"]]
        before = [path.read_bytes() for path in paths]
        source = copy.deepcopy(self.source)
        first = self.authorize()
        self.assertEqual(first, self.authorize())
        self.assertEqual(first, json.loads(json.dumps(first)))
        for row in first["checks"]:
            self.assertTrue({"component", "path", "status", "reason"}.issubset(row))
        self.assertEqual(source, self.source)
        self.assertEqual(before, [path.read_bytes() for path in paths])

    def test_schema_extension_is_optional_and_rejects_authorization_overrides(self):
        schema = validation.read_document(fixtures.ROOT / "schemas/content-item.schema.json")
        validator = RegistryValidator(schema)
        self.assertEqual(list(validator.iter_errors(self.source)), [])
        old = copy.deepcopy(self.source)
        old.pop("cta_mechanics")
        self.assertEqual(list(validator.iter_errors(old)), [])
        self.source["cta_mechanics"]["authorized"] = True
        self.assertTrue(list(validator.iter_errors(self.source)))

    def test_content_validator_checks_cta_after_applicability(self):
        self.source["cta_mechanics"]["conversion_path"] = "invented-path"
        result = validation.validate_content(self.source, mode="public", claims_path=self.root / "knowledge/claims.yaml", evidence_path=self.root / "knowledge/evidence.yaml", repository_root=self.root)
        self.assertFalse(result["continue"])
        self.assert_rejected(result["cta_authorization"], "conversion_path")

    def test_unauthorized_cta_prevents_export_and_remains_terminal(self):
        checkpoint = self.checkpoint(self.path)
        self.source["cta_mechanics"]["delivery_asset"] = "Invented asset"
        self.write_yaml(self.path, self.source)
        with patch.object(workflow, "markdown") as export:
            first = self.finalize(self.path, checkpoint, "public")
        self.assertFalse(first["continue"])
        self.assertEqual(first["phase"], "cta_authorization")
        self.assert_rejected(first["cta_authorization"], "delivery_asset")
        export.assert_not_called()
        self.assertFalse(self.path.with_suffix(".md").exists())
        self.assertEqual(validation.read_document(self.path.with_suffix(".validation-failure.json")), first)
        self.source["cta_mechanics"]["delivery_asset"] = "Fixture-only asset"
        self.write_yaml(self.path, self.source)
        self.assertEqual(self.finalize(self.path, checkpoint, "public"), first)

    def test_authorized_wording_variations_export_successfully(self):
        for wording in ["Comment FIXTURE for the fixture guide.", "Want the same guide? Use FIXTURE to request it."]:
            with self.subTest(wording=wording):
                self.source["cta"] = wording
                next(item for item in self.source["assertions"] if item["target"] == "/cta")["text"] = wording
                self.write_yaml(self.path, self.source)
                result = self.finalize(self.path, self.checkpoint(self.path), "public")
                self.assertTrue(result["valid"], result)
                self.assertTrue(result["cta_authorization"]["authorized"])
                self.assertIn(wording, self.path.with_suffix(".md").read_text())

    def test_cli_returns_nonzero_for_unauthorized_cta(self):
        checkpoint = self.checkpoint(self.path)
        self.source["cta_mechanics"]["account"] = "@invented_account"
        self.write_yaml(self.path, self.source)
        runner = ("import sys; from pathlib import Path; from scripts import carousel_workflow as w; "
                  "original=w.finalize_carousel; root=Path(sys.argv[1]); "
                  "w.finalize_carousel=lambda *args, **kwargs: original(*args, **kwargs, repository_root=root); "
                  "sys.argv=[sys.argv[0], *sys.argv[2:]]; raise SystemExit(w.main())")
        process = subprocess.run([sys.executable, "-B", "-c", runner, str(self.root), "finalize", str(self.path), "--strategy", str(checkpoint), "--status", "public"], capture_output=True, text=True)
        self.assertEqual(process.returncode, 1, process.stderr)
        self.assert_rejected(json.loads(process.stdout)["cta_authorization"], "account")

    def test_legacy_manthan_compatibility_is_explicitly_limited(self):
        path = self.content("manthan")
        result = self.finalize(path, self.checkpoint(path), "approved")
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["cta_authorization"]["coverage"], "legacy declared-source compatibility; rendered mechanics are not structurally authorized")
        self.assertFalse(result["cta_authorization"]["authorized"])
        self.assertIn("CTA authorization: PASS authorized=false coverage=legacy declared-source compatibility", path.with_suffix(".md").read_text())

    def test_malformed_input_or_mode_returns_failure_report(self):
        for content, mode in [(None, "public"), ([], "public"), (dict(self.source, assertions=None), "public"),
                              (dict(self.source, slides=None), "public"), (dict(self.source, status=[]), "public"),
                              (dict(self.source, profile_id="another-creator"), "public"),
                              (self.source, "invented"), (self.source, ["public"])]:
            with self.subTest(content=content, mode=mode):
                self.assert_rejected(validation.authorize_cta(content, mode=mode, repository_root=self.root), "configuration")

    def test_malformed_or_out_of_scope_configuration_fails_closed(self):
        paths = [self.root / "profiles/active.yaml", self.root / "profiles/mustafa/profile.yaml",
                 self.root / "profiles/mustafa/offers.yaml", self.root / "profiles/mustafa/channels.yaml"]
        original = [validation.read_document(path) for path in paths]
        cases = [(paths[1], lambda data: data.update(files=None)),
                 (paths[1], lambda data: data["files"].update(offers="../../../outside.yaml")),
                 (paths[1], lambda data: data["files"].update(offers="TODO_VERIFY")),
                 (paths[2], lambda data: data.update(offers=None)),
                 (paths[3], lambda data: data.update(channels=None))]
        for path, mutate in cases:
            with self.subTest(path=path, mutate=mutate):
                for target, data in zip(paths, original):
                    self.write_yaml(target, copy.deepcopy(data))
                data = validation.read_document(path)
                mutate(data)
                self.write_yaml(path, data)
                self.assert_rejected(self.authorize(), "configuration")
        for target, data in zip(paths, original):
            self.write_yaml(target, data)
        self.change("offers.yaml", lambda data: data["cta_policy"].update(enabled=False))
        text = paths[2].read_text()
        paths[2].write_text(text + "cta_policy:\n  enabled: true\n")
        self.assert_rejected(self.authorize(), "configuration")
        self.omit_cta()
        self.assert_rejected(self.authorize("draft"), "configuration")

    def test_channel_must_explicitly_support_carousels(self):
        for types in [None, [], ["text"], ["carousel", "TODO_VERIFY"]]:
            with self.subTest(types=types):
                self.change("channels.yaml", lambda data: data["channels"][0].update(content_types=types))
                self.assert_rejected(self.authorize(), "channel_content_types")

    def test_selected_record_disabled_flags_are_not_overridden_by_ready_status(self):
        for name, records, component in [("offers.yaml", "offers", "offer_enabled"), ("channels.yaml", "channels", "channel_enabled")]:
            for enabled in [False, None, "true", 1]:
                with self.subTest(name=name, enabled=enabled):
                    self.change(name, lambda data: data[records][0].update(enabled=enabled))
                    self.assert_rejected(self.authorize(), component)

    def test_matching_malformed_destination_is_not_authorized(self):
        for destination in ["example.test/fixture", "ftp://example.test/fixture", "https:///fixture", "https://example.test/fixture guide"]:
            with self.subTest(destination=destination):
                self.source["cta_mechanics"]["destination"] = destination
                self.change("offers.yaml", lambda data: data["cta_policy"].update(destination_url=destination))
                self.assert_rejected(self.authorize(), "destination")

    def test_public_preparation_requires_independent_conversion_path_before_generation(self):
        self.change("offers.yaml", lambda data: data["cta_policy"].pop("conversion_path"))
        arguments = "--profile mustafa A fixture core idea."
        prepared = workflow.resolve_request(arguments, self.root, mode="public")
        self.assertFalse(prepared["continue"])
        self.assertEqual(prepared["phase"], "readiness")
        self.assertTrue(any(error["code"] == "READINESS_BLOCKED" and error["path"].endswith("cta_policy.conversion_path") for error in prepared["errors"]))
        private = workflow.resolve_request(arguments, self.root)
        self.assertTrue(private["continue"])
        self.assertFalse(private["readiness"]["cta_ready"])

    def test_export_boundary_rechecks_changed_authoritative_configuration(self):
        checkpoint = self.checkpoint(self.path)
        original = validation.validate_content

        def change_after_validation(*args, **kwargs):
            result = original(*args, **kwargs)
            self.assertTrue(result["valid"], result)
            self.change("offers.yaml", lambda data: data["cta_policy"].update(delivery_asset="Changed fixture asset"))
            return result

        with patch.object(validation, "validate_content", side_effect=change_after_validation), patch.object(workflow, "markdown") as export:
            result = self.finalize(self.path, checkpoint, "public")
        self.assert_rejected(result["cta_authorization"], "delivery_asset")
        self.assertFalse(result["continue"])
        self.assertFalse(result["validation"]["continue"])
        self.assertEqual(result["phase"], "cta_authorization")
        export.assert_not_called()

    def test_validator_pass_cannot_bypass_export_authorization(self):
        checkpoint = self.checkpoint(self.path)
        self.source["cta_mechanics"]["destination"] = "https://example.test/invented"
        self.write_yaml(self.path, self.source)
        with patch.object(validation, "validate_content", return_value={"valid": True, "result": "PASS", "errors": []}), patch.object(workflow, "markdown") as export:
            result = self.finalize(self.path, checkpoint, "public")
        self.assert_rejected(result["cta_authorization"], "destination")
        self.assertFalse(result["continue"])
        export.assert_not_called()

    def test_malformed_authorization_responses_cannot_export(self):
        responses = [None, [], {"valid": True, "result": "FAIL", "errors": []},
                     {"valid": "true", "result": "PASS", "errors": []},
                     {"valid": True, "result": "PASS", "errors": ["untrusted"]},
                     {"valid": True, "result": "PASS", "errors": [], "authorized": False},
                     {"valid": True, "result": "PASS", "errors": [], "continue": True, "authorized": "true"},
                     {"valid": True, "result": "PASS", "errors": [], "continue": False, "authorized": True},
                     {"valid": True, "result": "PASS", "errors": [], "continue": True, "authorized": False}]
        for response in responses:
            with self.subTest(response=response):
                path = self.content("mustafa")
                checkpoint = self.checkpoint(path)
                with patch.object(validation, "validate_content", return_value={"valid": True, "result": "PASS", "errors": []}), patch.object(validation, "authorize_cta", return_value=response), patch.object(workflow, "markdown") as export:
                    result = self.finalize(path, checkpoint, "public")
                self.assertFalse(result["continue"])
                self.assertFalse(result["cta_authorization"]["valid"])
                self.assertFalse(result["cta_authorization"]["authorized"])
                self.assertEqual(result["phase"], "cta_authorization")
                export.assert_not_called()
                self.assertEqual(validation.read_document(path.with_suffix(".validation-failure.json")), result)

    def test_offer_contract_accepts_explicit_policy_fields_and_requires_boolean_permissions(self):
        schema = validation.read_document(fixtures.ROOT / "schemas/offer.schema.json")
        validator = RegistryValidator(schema)
        offers = validation.read_document(self.root / "profiles/mustafa/offers.yaml")
        offers["status"] = "complete"  # Schema completeness, separate from selected offer status.
        offers["cta_policy"].update(enabled=True, publishable=True, status="configured", public_use="public")
        offers["offers"][0].update(enabled=True, public_use="public")
        self.assertEqual(list(validator.iter_errors(offers)), [])
        offers["cta_policy"]["enabled"] = "true"
        self.assertTrue(list(validator.iter_errors(offers)))


if __name__ == "__main__":
    unittest.main()
