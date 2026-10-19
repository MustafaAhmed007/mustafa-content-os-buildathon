"""Deterministic readiness gates using temporary copies, never creator repairs."""

import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import yaml

import test_carousel_integration as integration
from scripts import carousel_workflow as workflow


class CarouselReadinessTests(unittest.TestCase):
    setUp = integration.CarouselIntegrationTests.setUp
    write_yaml = integration.CarouselIntegrationTests.write_yaml
    write_frontmatter = integration.CarouselIntegrationTests.write_frontmatter
    content = integration.CarouselIntegrationTests.content
    checkpoint = integration.CarouselIntegrationTests.checkpoint
    finalize = integration.CarouselIntegrationTests.finalize
    complete_mustafa_fixture = integration.CarouselIntegrationTests.complete_mustafa_fixture

    def ready(self, mode="draft"):
        return workflow.resolve_request("--profile mustafa Fixture-only readiness idea.", self.root, mode=mode)

    def metadata(self, name):
        path = self.root / "profiles/mustafa" / name
        if path.suffix == ".md":
            return yaml.safe_load(path.read_text().split("---", 2)[1])
        return workflow.validator.read_document(path)

    def change(self, name, mutate):
        data = self.metadata(name)
        mutate(data)
        path = self.root / "profiles/mustafa" / name
        if path.suffix == ".md":
            self.write_frontmatter(path, data)
        else:
            self.write_yaml(path, data)

    def assert_blocked(self, result, path_fragment):
        self.assertFalse(result["valid"], result)
        self.assertEqual(result["result"], "FAIL")
        self.assertFalse(result["continue"])
        self.assertEqual(result["phase"], "readiness")
        self.assertTrue(any(row["blocking"] and path_fragment in row["path"] for row in result["readiness"]["checks"]), result)
        self.assertIn("READINESS_BLOCKED", {error["code"] for error in result["errors"]})

    def test_nested_required_identity_sentinels_block_drafting(self):
        self.complete_mustafa_fixture()
        for value in ["TODO_VERIFY", "unresolved", "incomplete", "placeholder", "<name>", "", None]:
            with self.subTest(value=value):
                self.change("identity.md", lambda data: data["identity"].update(name=value))
                self.assert_blocked(self.ready(), "identity.name")

    def test_missing_required_identity_field_blocks_drafting(self):
        self.complete_mustafa_fixture()
        self.change("identity.md", lambda data: data["identity"].pop("name"))
        self.assert_blocked(self.ready(), "identity.name")

    def test_required_voice_rule_with_nested_sentinel_blocks_drafting(self):
        self.complete_mustafa_fixture()
        self.change("voice.md", lambda data: data.update(tone=["direct", "TODO_VERIFY"]))
        self.assert_blocked(self.ready(), "tone")

    def test_unresolved_novelty_rules_and_gate_status_block_drafting(self):
        self.complete_mustafa_fixture()
        original = self.metadata("strategy.md")
        for field in ["configured_rules", "status"]:
            with self.subTest(field=field):
                self.write_frontmatter(self.root / "profiles/mustafa/strategy.md", original)
                self.change("strategy.md", lambda data: data["novelty_gate"].update({field: "TODO_VERIFY"}))
                self.assert_blocked(self.ready(), "novelty_gate." + field)

    def test_missing_configured_novelty_rule_blocks_drafting(self):
        self.complete_mustafa_fixture()
        self.change("strategy.md", lambda data: data["novelty_gate"]["configured_rules"].pop("one_of_none"))
        self.assert_blocked(self.ready(), "configured_rules.one_of_none")

    def test_unconfigured_active_pillar_blocks_drafting(self):
        self.complete_mustafa_fixture()
        self.change("strategy.md", lambda data: data.update(active_pillar_ids=[]))
        self.assert_blocked(self.ready(), "active_pillar_ids")

    def test_candidate_pillar_and_unresolved_selection_status_block_drafting(self):
        self.complete_mustafa_fixture()
        self.change("strategy.md", lambda data: data.update(active_selection_status="TODO_VERIFY"))
        self.change("strategy.md", lambda data: data["pillars"][0].update(status="candidate"))
        result = self.ready()
        self.assert_blocked(result, "active_selection_status")
        self.assert_blocked(result, "pillars[fixture-workflows].status")

    def test_unresolved_instagram_handle_allows_draft_but_blocks_public(self):
        self.complete_mustafa_fixture()
        self.change("channels.yaml", lambda data: data["channels"][0].update(handle_or_url="TODO_VERIFY"))
        before = (self.root / "profiles/mustafa/channels.yaml").read_bytes()
        draft = self.ready()
        self.assertTrue(draft["valid"], draft)
        self.assertTrue(draft["readiness"]["draft_ready"])
        self.assertFalse(draft["readiness"]["public_ready"])
        self.assert_blocked(self.ready("public"), "handle_or_url")
        self.assertEqual(before, (self.root / "profiles/mustafa/channels.yaml").read_bytes())

    def test_explicitly_unavailable_instagram_is_private_only(self):
        self.complete_mustafa_fixture()
        self.change("channels.yaml", lambda data: data["channels"][0].update(handle_or_url="unavailable", status="unavailable", publishable=False))
        self.assertTrue(self.ready()["valid"])
        self.assert_blocked(self.ready("public"), "channels[instagram]")

    def test_missing_selected_channel_does_not_fall_back_to_other_account(self):
        self.complete_mustafa_fixture()
        self.change("channels.yaml", lambda data: data["channels"][0].update(id="github", platform="GitHub"))
        self.assert_blocked(self.ready("public"), "channels[instagram]")

    def test_channel_without_carousel_configuration_blocks_public_only(self):
        self.complete_mustafa_fixture()
        self.change("channels.yaml", lambda data: data["channels"][0].update(content_types=["repositories"]))
        self.assertTrue(self.ready()["valid"])
        self.assert_blocked(self.ready("public"), "content_types")

    def test_unresolved_cta_keyword_blocks_publication(self):
        self.complete_mustafa_fixture()
        self.change("offers.yaml", lambda data: data["cta_policy"].update(keyword="TODO_VERIFY"))
        self.assertTrue(self.ready()["valid"])
        self.assertFalse(self.ready()["readiness"]["cta_ready"])
        self.assert_blocked(self.ready("public"), "cta_policy.keyword")

    def test_unresolved_cta_destination_blocks_publication(self):
        self.complete_mustafa_fixture()
        self.change("offers.yaml", lambda data: data["cta_policy"].update(destination_url="TODO_VERIFY"))
        self.assert_blocked(self.ready("public"), "cta_policy.destination_url")

    def test_unresolved_cta_asset_and_conversion_path_block_publication(self):
        self.complete_mustafa_fixture()
        self.change("offers.yaml", lambda data: data["cta_policy"].update(delivery_asset="TODO_VERIFY", primary_mechanic="unresolved"))
        result = self.ready("public")
        self.assert_blocked(result, "cta_policy.delivery_asset")
        self.assert_blocked(result, "cta_policy.primary_mechanic")

    def test_unresolved_offer_configuration_blocks_publication(self):
        self.complete_mustafa_fixture()
        self.change("offers.yaml", lambda data: data["offers"][0].update(description="TODO_VERIFY", status="incomplete", publishable=False))
        self.assert_blocked(self.ready("public"), "offers[fixture-offer]")

    def test_unresolved_or_missing_offer_selection_blocks_publication(self):
        self.complete_mustafa_fixture()
        for value in ["TODO_VERIFY", "absent-offer"]:
            with self.subTest(value=value):
                self.change("offers.yaml", lambda data: data["cta_policy"].update(offer_selection=value))
                self.assert_blocked(self.ready("public"), "offer_selection")

    def test_fabricated_true_checkpoint_cannot_override_current_readiness(self):
        self.complete_mustafa_fixture()
        path = self.content("mustafa")
        context = workflow.resolve_request(f"--profile mustafa {workflow.validator.read_document(path)['idea']}", self.root)
        checkpoint = self.checkpoint(path)
        self.change("strategy.md", lambda data: data["novelty_gate"].update(configured_rules="TODO_VERIFY"))
        report = json.loads(checkpoint.read_text())
        report["source_sha256"] = workflow.sha256(self.root / report["source"])
        result = workflow.check_strategy(report, context, self.root)
        self.assert_blocked(result, "novelty_gate.configured_rules")

    def test_readiness_failure_prevents_validation_export_and_continuation(self):
        self.complete_mustafa_fixture()
        path = self.content("mustafa")
        checkpoint = self.checkpoint(path)
        self.change("offers.yaml", lambda data: data["cta_policy"].update(destination_url="TODO_VERIFY"))
        with patch.object(workflow.validator, "validate_content") as validate, patch.object(workflow, "markdown") as export:
            result = self.finalize(path, checkpoint, "public")
        self.assert_blocked(result, "cta_policy.destination_url")
        validate.assert_not_called()
        export.assert_not_called()
        self.assertIsNone(result["validation"])
        self.assertFalse(path.with_suffix(".md").exists())
        self.assertEqual(workflow.validator.read_document(path)["status"], "draft")
        self.assertEqual(workflow.validator.read_document(path.with_suffix(".validation-failure.json")), result)

    def test_readiness_failure_revokes_old_pass_and_remains_terminal(self):
        self.complete_mustafa_fixture()
        path = self.content("mustafa")
        self.assertTrue(self.finalize(path, self.checkpoint(path), "approved")["valid"])
        self.change("channels.yaml", lambda data: data["channels"][0].update(publishable=False))
        first = self.finalize(path, status="public")
        self.assert_blocked(first, "publishable")
        self.assertNotIn("Validation: PASS", path.with_suffix(".md").read_text())
        self.change("channels.yaml", lambda data: data["channels"][0].update(publishable=True))
        self.assertEqual(self.finalize(path, status="public"), first)

    def test_fully_configured_profile_passes_public_readiness_and_export(self):
        self.complete_mustafa_fixture()
        result = self.ready("public")
        self.assertTrue(result["valid"], result)
        self.assertTrue(result["continue"])
        self.assertTrue(result["readiness"]["public_ready"])
        path = self.content("mustafa")
        self.assertTrue(self.finalize(path, self.checkpoint(path), "public")["valid"])

    def test_optional_unknown_fields_do_not_block_drafting_or_public_readiness(self):
        self.complete_mustafa_fixture()
        self.assertEqual(self.metadata("identity.md")["identity"]["legal_identity"], "TODO_VERIFY")
        self.assertEqual(self.metadata("strategy.md")["pillars"][0]["rank"], "TODO_VERIFY")
        self.assertEqual(self.metadata("offers.yaml")["offers"][0]["proof"], "TODO_VERIFY")
        self.assertTrue(self.ready()["valid"])
        self.assertTrue(self.ready("public")["valid"])

    def test_private_body_draft_allowed_but_unconfigured_cta_cannot_be_generated(self):
        self.complete_mustafa_fixture()
        path = self.content("mustafa")
        checkpoint = self.checkpoint(path)
        self.change("offers.yaml", lambda data: data["cta_policy"].update(keyword="TODO_VERIFY"))
        source = workflow.validator.read_document(path)
        source["cta"] = ""
        source["slides"][-1]["body"] = ""
        source["slides"][-1]["headline"] = ""
        self.write_yaml(path, source)
        draft = self.finalize(path, checkpoint, "draft")
        self.assertTrue(draft["valid"], draft)
        self.assertFalse(draft["readiness"]["cta_ready"])
        source["cta"] = "Comment an invented keyword."
        self.write_yaml(path, source)
        self.assert_blocked(self.finalize(path, status="draft"), "content.cta")

    def test_selected_content_pillar_must_be_configured(self):
        self.complete_mustafa_fixture()
        path = self.content("mustafa")
        checkpoint = self.checkpoint(path)
        source = workflow.validator.read_document(path)
        source["pillar"] = "Unconfigured fixture pillar"
        self.write_yaml(path, source)
        self.assert_blocked(self.finalize(path, checkpoint), "content.pillar")

    def test_report_is_deterministic_machine_readable_and_read_only(self):
        self.complete_mustafa_fixture()
        paths = sorted((self.root / "profiles/mustafa").glob("*"))
        before = [path.read_bytes() for path in paths]
        first = self.ready("public")
        self.assertEqual(first, self.ready("public"))
        self.assertEqual(json.loads(json.dumps(first)), first)
        for row in first["readiness"]["checks"]:
            self.assertTrue({"profile", "check", "path", "status", "reason", "blocking"}.issubset(row))
            self.assertIn(row["status"], {"PASS", "FAIL"})
            self.assertIsInstance(row["blocking"], bool)
        self.assertEqual(before, [path.read_bytes() for path in paths])

    def test_malformed_or_wrong_profile_frontmatter_fails_readiness(self):
        self.complete_mustafa_fixture()
        self.change("identity.md", lambda data: data.update(profile_id="other"))
        self.assert_blocked(self.ready(), "identity.md#profile_id")
        (self.root / "profiles/mustafa/identity.md").write_text("---\nidentity: [\n---\n")
        self.assert_blocked(self.ready(), "identity.md")

    def test_strategy_checksum_binding_survives_readiness_enforcement(self):
        self.complete_mustafa_fixture()
        path = self.content("mustafa")
        checkpoint = self.checkpoint(path)
        strategy = self.root / "profiles/mustafa/strategy.md"
        strategy.write_text(strategy.read_text() + "\nFixture-only source edit.\n")
        result = self.finalize(path, checkpoint)
        self.assertFalse(result["valid"])
        self.assertIn("STRATEGY_GATE_FAILED", {error["code"] for error in result["errors"]})

    def test_changed_strategy_source_map_cannot_reuse_old_context_binding(self):
        self.complete_mustafa_fixture()
        path = self.content("mustafa")
        source = workflow.validator.read_document(path)
        context = workflow.resolve_request(f"--profile mustafa {source['idea']}", self.root)
        report = json.loads(self.checkpoint(path).read_text())
        alternate = self.root / "profiles/mustafa/alternate-strategy.md"
        alternate.write_bytes((self.root / "profiles/mustafa/strategy.md").read_bytes())
        self.change("profile.yaml", lambda data: data["files"].update(strategy="alternate-strategy.md"))
        result = workflow.check_strategy(report, context, self.root)
        self.assertFalse(result["valid"], result)
        self.assertIn("STRATEGY_GATE_FAILED", {error["code"] for error in result["errors"]})

    def test_unselected_unknown_channels_and_offers_do_not_block_public_readiness(self):
        self.complete_mustafa_fixture()
        self.change("channels.yaml", lambda data: data.update(status="incomplete"))
        self.change("channels.yaml", lambda data: data["channels"].append({"id": "youtube", "handle_or_url": "TODO_VERIFY", "status": "incomplete"}))
        self.change("offers.yaml", lambda data: data["offers"].append({"id": "unused-offer", "status": "TODO_VERIFY"}))
        self.assertTrue(self.ready("public")["valid"])

    def test_optional_unresolved_cta_source_allows_body_drafting_only(self):
        self.complete_mustafa_fixture()
        self.change("profile.yaml", lambda data: data["files"].update(offers="TODO_VERIFY", business="TODO_VERIFY"))
        draft = self.ready()
        self.assertTrue(draft["valid"], draft)
        self.assertFalse(draft["readiness"]["cta_ready"])
        self.assert_blocked(self.ready("public"), "files.offers")

    def test_invalid_cta_destination_or_permission_blocks_publication(self):
        for changes in [{"destination_url": "not-a-url"}, {"public_use": "needs_approval"}]:
            with self.subTest(changes=changes):
                self.complete_mustafa_fixture()
                self.change("offers.yaml", lambda data: data["cta_policy"].update(changes))
                self.assert_blocked(self.ready("public"), "cta_policy")

    def test_draft_profile_status_allows_private_work_but_blocks_public(self):
        self.complete_mustafa_fixture()
        self.change("profile.yaml", lambda data: data.update(status="draft"))
        self.assertTrue(self.ready()["valid"])
        self.assert_blocked(self.ready("public"), "profile.yaml#status")

    def test_finalize_cli_readiness_failure_is_not_content_validation(self):
        self.complete_mustafa_fixture()
        path = self.content("mustafa")
        checkpoint = self.checkpoint(path)
        self.change("offers.yaml", lambda data: data["cta_policy"].update(keyword="TODO_VERIFY"))
        runner = (
            "import sys; from pathlib import Path; from scripts import carousel_workflow as w; "
            "original=w.finalize_carousel; root=Path(sys.argv[1]); "
            "w.finalize_carousel=lambda *args, **kwargs: original(*args, **kwargs, repository_root=root); "
            "sys.argv=[sys.argv[0], *sys.argv[2:]]; raise SystemExit(w.main())"
        )
        process = subprocess.run([sys.executable, "-B", "-c", runner, str(self.root), "finalize", str(path), "--strategy", str(checkpoint), "--status", "public"], capture_output=True, text=True)
        self.assertEqual(process.returncode, 1, process.stderr)
        result = json.loads(process.stdout)
        self.assert_blocked(result, "cta_policy.keyword")
        self.assertIsNone(result["validation"])
        self.assertFalse(path.with_suffix(".md").exists())

    def test_prepare_cli_blocks_before_generation_with_actionable_report(self):
        self.complete_mustafa_fixture()
        self.change("strategy.md", lambda data: data.update(active_selection_status="TODO_VERIFY"))
        runner = (
            "import sys; from pathlib import Path; from scripts import carousel_workflow as w; "
            "original=w.resolve_request; root=Path(sys.argv[1]); "
            "w.resolve_request=lambda raw, **kwargs: original(raw, root, **kwargs); "
            "sys.argv=[sys.argv[0], *sys.argv[2:]]; raise SystemExit(w.main())"
        )
        process = subprocess.run([sys.executable, "-B", "-c", runner, str(self.root), "prepare", "--mode", "public", "--", "--profile mustafa Fixture-only idea."], capture_output=True, text=True)
        self.assertEqual(process.returncode, 1, process.stderr)
        self.assert_blocked(json.loads(process.stdout), "active_selection_status")
        self.assertFalse(list((self.root / "content/carousels").iterdir()))

    def test_existing_manthan_draft_and_public_readiness_remain_valid(self):
        for mode in ["draft", "public"]:
            with self.subTest(mode=mode):
                result = workflow.resolve_request("Fixture-only legacy idea.", self.root, mode=mode)
                self.assertTrue(result["valid"], result)
                self.assertEqual(result["profile"], "manthan")
                self.assertTrue(result["readiness"]["public_ready"])


if __name__ == "__main__":
    unittest.main()
