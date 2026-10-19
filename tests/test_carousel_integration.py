"""Real validation/gate integration using isolated content and profile fixtures."""

import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

from scripts import carousel_workflow as workflow
from scripts import artifact_state


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FIXTURE_ROOT = ROOT / "tests/fixtures/public"
FIXTURES = ROOT / "tests/fixtures/public/carousel"
SCRIPT = ROOT / "scripts/carousel_workflow.py"


class CarouselIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        sources = {
            "profiles/active.yaml": PUBLIC_FIXTURE_ROOT / "repository/profiles/active.yaml",
            "profiles/manthan/profile.yaml": PUBLIC_FIXTURE_ROOT / "repository/profiles/legacy/profile.yaml",
            "profiles/mustafa/profile.yaml": PUBLIC_FIXTURE_ROOT / "repository/profiles/structured/profile.yaml",
        }
        legacy = workflow.validator.read_document(sources["profiles/manthan/profile.yaml"])
        sources.update({value: PUBLIC_FIXTURE_ROOT / "repository" / value for value in legacy["legacy_sources"].values()})
        manifest = workflow.validator.read_document(sources["profiles/mustafa/profile.yaml"])
        sources.update({
            "profiles/mustafa/" + value: PUBLIC_FIXTURE_ROOT / "repository/profiles/structured" / value
            for value in manifest["files"].values() if value != "TODO_VERIFY"
        })
        for path in (PUBLIC_FIXTURE_ROOT / "knowledge").rglob("*.yaml"):
            sources[str(path.relative_to(PUBLIC_FIXTURE_ROOT))] = path
        for name in workflow.SYSTEM_SOURCES:
            sources[name] = ROOT / name
        for name, source in sources.items():
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        (self.root / "content/carousels").mkdir(parents=True)

    def write_yaml(self, path, data):
        if isinstance(data, dict) and data.get("content_id") == "2099-01-01-fixture-mustafa" and isinstance(data.get("assertions"), list):
            # Drop our scaffold annotations when another phase's fixture omits copy.
            # Author-supplied factual assertion bindings are never repaired here.
            retained = []
            for assertion in data["assertions"]:
                if assertion.get("assertion_id", "").startswith("fixture-") and assertion.get("assertion_type") == "non_factual":
                    parts = assertion["target"].split("/")[1:]
                    current = data.get(parts[0]) if len(parts) == 1 else data.get("slides", [])[int(parts[1])].get(parts[2])
                    if not current:
                        continue
                retained.append(assertion)
            data["assertions"] = retained
            if not data.get("cta") and not any(slide.get("role") == "cta" and (slide.get("headline") or slide.get("body")) for slide in data.get("slides", [])):
                data.pop("cta_mechanics", None)  # Omitted scaffold CTA has no mechanics.
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))

    def write_frontmatter(self, path, data):
        path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False, allow_unicode=True) + "---\n\n# Fixture-only context\n")

    def content(self, profile):
        source = FIXTURES / f"2099-01-01-fixture-{profile}.yaml"
        path = self.root / "content/carousels" / source.name
        # Each fixture installation starts an independent test run.
        failure = path.with_suffix(".validation-failure.json")
        if failure.exists():
            failure.unlink()
        state = path.parent / ".workflow-state"
        if state.exists():
            shutil.rmtree(state)
        path.write_bytes(source.read_bytes())
        if profile == "mustafa":
            # Explicit classifications of test scaffold copy, not creator facts.
            data = workflow.validator.read_document(path)
            data["assertions"] = []
            for index, slide in enumerate(data["slides"]):
                for field in ("headline", "body", "visual_note"):
                    text = slide.get(field, "")
                    if text.startswith(("Fixture", "Pattern interrupt:")):
                        data["assertions"].append({"assertion_id": f"fixture-{index}-{field.replace('_', '-')}",
                                                   "target": f"/slides/{index}/{field}", "text": text,
                                                   "assertion_type": "non_factual", "claim_refs": []})
            data["assertions"].append({"assertion_id": "fixture-cta", "target": "/cta", "text": data["cta"],
                                       "assertion_type": "non_factual", "claim_refs": []})
            data["cta_mechanics"] = {"cta_type": "comment_keyword", "keyword": "FIXTURE", "offer_id": "fixture-offer",
                                     "destination": "https://example.test/fixture", "delivery_asset": "Fixture-only asset",
                                     "conversion_path": "fixture-comment-to-private-delivery", "account": "@fixture_account"}
            self.write_yaml(path, data)
        return path

    def incomplete_mustafa_fixture(self):
        path = self.root / "profiles/mustafa/profile.yaml"
        manifest = workflow.validator.read_document(path)
        manifest["status"] = "incomplete"
        manifest["files"]["design_system"] = "TODO_VERIFY"
        self.write_yaml(path, manifest)

    def complete_mustafa_fixture(self):
        # Local fixture only. The repository manifest/active profile are untouched.
        path = self.root / "profiles/mustafa/profile.yaml"
        manifest = workflow.validator.read_document(path)
        manifest["status"] = "active"
        manifest["files"]["design_system"] = "fixture-design.md"
        self.write_yaml(path, manifest)
        (path.parent / "fixture-design.md").write_text("# Fixture design context\n")
        self.write_frontmatter(path.parent / "strategy.md", {
            "schema_version": "1.0", "profile_id": "mustafa", "status": "active",
            "active_selection_status": "verified", "active_pillar_ids": ["fixture-workflows"],
            "pillars": [{"id": "fixture-workflows", "name": "Fixture-only workflow testing", "status": "active", "rank": "TODO_VERIFY"}],
            "novelty_gate": {"status": "configured", "configured_rules": {name: "Fixture-only configured rule." for name in workflow.GATES}},
        })
        self.write_yaml(path.parent / "channels.yaml", {
            "schema_version": "1.0", "profile_id": "mustafa", "status": "active",
            "channels": [{"id": "instagram", "platform": "Instagram", "handle_or_url": "@fixture_account",
                          "content_types": ["carousel"], "status": "verified", "publishable": True,
                          "public_use": "public", "verification_status": "verified"}],
            "publishing": {"default_timezone": "TODO_VERIFY", "scheduling_time": "TODO_VERIFY"},
        })
        self.write_yaml(path.parent / "offers.yaml", {
            "schema_version": "1.0", "profile_id": "mustafa", "status": "active", "public_use": "public",
            "offers": [{"id": "fixture-offer", "name": "Fixture-only offer", "description": "Fixture-only delivery scope.",
                        "target_customer": "Fixture-only audience", "status": "active", "publishable": True,
                        "pricing": "TODO_VERIFY", "proof": "TODO_VERIFY"}],
            "cta_policy": {"primary_mechanic": "comment_keyword", "keyword": "FIXTURE",
                            "delivery_asset": "Fixture-only asset", "destination_url": "https://example.test/fixture",
                            "offer_selection": "fixture-offer", "conversion_path": "fixture-comment-to-private-delivery",
                            "allow_private_draft_without_cta": True},
        })

    def checkpoint(self, path):
        content = workflow.validator.read_document(path)
        context = workflow.resolve_request(f"--profile {content['profile']} {content['idea']}", self.root)
        self.assertTrue(context["valid"], context)
        report = {
            "profile": content["profile"], "idea": content["idea"],
            "source": context["sources"]["strategy"],
            "source_sha256": context["strategy_source_sha256"],
            "gates": {name: {"pass": True, "reason": "Fixture-only affirmative judgment."} for name in workflow.GATES},
        }
        target = self.root / "checkpoint.json"
        target.write_text(json.dumps(report))
        return target

    def finalize(self, path, checkpoint=None, status=None, notes=None):
        return workflow.finalize_carousel(path, checkpoint, notes, status, self.root)

    def assert_failure(self, result, code):
        self.assertFalse(result["valid"], result)
        self.assertEqual(result["result"], "FAIL")
        self.assertIn(code, {error["code"] for error in result["errors"]}, result)
        if "continue" in result:
            self.assertFalse(result["continue"])

    def test_default_selection_preserves_legacy_manthan_sources(self):
        before = (self.root / "profiles/active.yaml").read_bytes()
        context = workflow.resolve_request("A fixture core idea.", self.root)
        self.assertTrue(context["valid"], context)
        self.assertEqual(context["profile"], "manthan")
        self.assertEqual(context["mode"], "legacy-reference")
        self.assertEqual(context["sources"]["identity"], "fixture-identity.md")
        self.assertEqual(context["sources"]["strategy"], "fixture-strategy.md")
        self.assertEqual((self.root / "profiles/active.yaml").read_bytes(), before)

    def test_explicit_mustafa_selection_keeps_fixture_context_blockers(self):
        before = (self.root / "profiles/active.yaml").read_bytes()
        self.incomplete_mustafa_fixture()
        context = workflow.resolve_request("--profile mustafa A fixture core idea.", self.root)
        self.assertEqual(context["profile"], "mustafa")
        self.assertEqual(context["active_profile"], "manthan")
        self.assert_failure(context, "INCOMPLETE_PROFILE")
        self.assert_failure(context, "UNRESOLVED_PROFILE_SOURCE")
        self.assertEqual(context["sources"]["identity"], "profiles/mustafa/identity.md")
        self.assertEqual((self.root / "profiles/active.yaml").read_bytes(), before)

    def test_selection_preserves_apostrophes_and_rejects_unknown_options_profiles_or_empty_ideas(self):
        self.assertEqual(workflow.resolve_request("I'm testing a fixture.", self.root)["idea"], "I'm testing a fixture.")
        for arguments, code in [
            ("", "MISSING_IDEA"), ("--profile mustafa", "MISSING_IDEA"),
            ("--profile absent Fixture", "UNKNOWN_PROFILE"),
            ("--other Fixture", "INVALID_ARGUMENTS"), ("--profile ../other Fixture", "INVALID_ARGUMENTS"),
        ]:
            with self.subTest(arguments=arguments):
                self.assert_failure(workflow.resolve_request(arguments, self.root), code)

    def test_complete_explicit_profile_fixture_resolves_without_global_switch(self):
        self.complete_mustafa_fixture()
        context = workflow.resolve_request("--profile mustafa A fixture idea.", self.root)
        self.assertTrue(context["valid"], context)
        self.assertEqual(context["profile"], "mustafa")
        self.assertEqual(workflow.validator.read_document(self.root / "profiles/active.yaml")["active_profile"], "manthan")

    def test_unresolved_path_is_not_probed_and_never_falls_back_to_legacy(self):
        self.incomplete_mustafa_fixture()
        original = Path.is_file
        def checked(path):
            self.assertNotIn("TODO_VERIFY", str(path))
            return original(path)
        with patch.object(Path, "is_file", checked):
            context = workflow.resolve_request("--profile mustafa Fixture", self.root)
        self.assert_failure(context, "UNRESOLVED_PROFILE_SOURCE")
        self.assertNotIn("personal-info.md", context["sources"].values())

    def test_default_generated_pair_has_profile_metadata_and_legacy_coverage(self):
        path = self.content("manthan")
        result = self.finalize(path, self.checkpoint(path))
        self.assertTrue(result["valid"], result)
        self.assertTrue(result["continue"])
        self.assertEqual(result["validation"]["profile"], "manthan")
        self.assertIn("no registered creator proof", result["registry_coverage"])
        markdown = path.with_suffix(".md").read_text()
        self.assertIn("| profile | manthan |", markdown)
        self.assertIn("| status | draft |", markdown)
        self.assertIn("Validation: PASS", markdown)
        self.assertEqual(workflow.validator.read_document(path)["claims"], [])

    def test_explicit_mustafa_generated_pair_contains_real_claim_references(self):
        self.complete_mustafa_fixture()
        path = self.content("mustafa")
        result = self.finalize(path, self.checkpoint(path))
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["registry_coverage"], "authoritative claim/evidence registries")
        output = workflow.validator.read_document(path)
        self.assertEqual(output["profile"], "mustafa")
        self.assertIn("mustafa-public-name", output["claims"])
        self.assertIn("mustafa-public-name", output["slides"][0]["claim_refs"])
        self.assertEqual(result["validation"]["claims"][0]["verification_status"], "self_reported")
        self.assertIn("| profile | mustafa |", path.with_suffix(".md").read_text())

    def test_validation_pass_allows_approved_state_only_after_public_checks(self):
        self.complete_mustafa_fixture()
        path = self.content("mustafa")
        checkpoint = self.checkpoint(path)
        with patch.object(workflow.validator, "validate_content", wraps=workflow.validator.validate_content) as called:
            result = self.finalize(path, checkpoint, "approved")
        self.assertTrue(result["valid"], result)
        self.assertTrue(result["validation"]["public_facing"])
        self.assertEqual(called.call_count, 1)
        self.assertEqual(called.call_args.kwargs["expected_profile"], "mustafa")
        self.assertEqual(workflow.validator.read_document(path)["status"], "approved")
        self.assertIn("| status | approved |", path.with_suffix(".md").read_text())

    def test_default_legacy_approval_still_works_without_creating_proof_records(self):
        path = self.content("manthan")
        before = [(self.root / "knowledge" / name).read_bytes() for name in ["claims.yaml", "evidence.yaml"]]
        result = self.finalize(path, self.checkpoint(path), "approved")
        self.assertTrue(result["valid"], result)
        self.assertTrue(result["validation"]["public_facing"])
        self.assertEqual(workflow.validator.read_document(path)["status"], "approved")
        self.assertEqual(before, [(self.root / "knowledge" / name).read_bytes() for name in ["claims.yaml", "evidence.yaml"]])
        self.assertFalse(list(path.parent.glob(".validation-*")))

    def test_validation_failure_blocks_approval_and_public_state(self):
        self.complete_mustafa_fixture()
        for status in ["approved", "public"]:
            with self.subTest(status=status):
                path = self.content("mustafa")
                checkpoint = self.checkpoint(path)
                content = workflow.validator.read_document(path)
                content["claims"] = ["fixture-unknown-claim"]
                self.write_yaml(path, content)
                result = self.finalize(path, checkpoint, status)
                self.assert_failure(result, "UNKNOWN_CLAIM")
                self.assertEqual(workflow.validator.read_document(path)["status"], "draft")
                self.assertFalse(path.with_suffix(".md").exists())
                self.assertEqual(workflow.validator.read_document(path.with_suffix(".validation-failure.json")), result)

    def test_restricted_claim_blocks_public_approval_but_allows_internal_review(self):
        self.complete_mustafa_fixture()
        path = self.content("mustafa")
        checkpoint = self.checkpoint(path)
        claims_path = self.root / "knowledge/claims.yaml"
        claims = workflow.validator.read_document(claims_path)
        claims["claims"][0]["public_use"] = "needs_approval"
        self.write_yaml(claims_path, claims)
        self.assertTrue(self.finalize(path, checkpoint, "review")["valid"])
        result = self.finalize(path, status="approved")
        self.assert_failure(result, "RESTRICTED_CLAIM")
        self.assertEqual(workflow.validator.read_document(path)["status"], "draft")

    def test_unknown_legacy_reference_is_not_silently_ignored(self):
        path = self.content("manthan")
        checkpoint = self.checkpoint(path)
        content = workflow.validator.read_document(path)
        content["claims"] = ["mustafa-public-name"]
        self.write_yaml(path, content)
        self.assert_failure(self.finalize(path, checkpoint), "UNKNOWN_CLAIM")

    def test_explicit_kill_keeps_invalid_content_non_ready_and_preserves_legacy_disposition(self):
        path = self.content("manthan")
        checkpoint = self.checkpoint(path)
        content = workflow.validator.read_document(path)
        content["claims"] = ["fixture-unknown-claim"]
        self.write_yaml(path, content)
        result = self.finalize(path, checkpoint, "killed")
        self.assert_failure(result, "UNKNOWN_CLAIM")
        self.assertEqual(workflow.validator.read_document(path)["status"], "killed")
        self.assertFalse(path.with_suffix(".md").exists())

    def test_weak_strategy_gates_stop_before_validator_or_output(self):
        path = self.content("manthan")
        checkpoint = self.checkpoint(path)
        initial = json.loads(checkpoint.read_text())
        for name in workflow.GATES:
            with self.subTest(gate=name):
                self.content("manthan")
                report = copy.deepcopy(initial)
                report["gates"][name]["pass"] = False
                checkpoint.write_text(json.dumps(report))
                with patch.object(workflow.validator, "validate_content") as validate:
                    result = self.finalize(path, checkpoint)
                validate.assert_not_called()
                self.assert_failure(result, "STRATEGY_GATE_FAILED")
                self.assertIsNone(result["validation"])
                self.assertFalse(path.with_suffix(".md").exists())

    def test_missing_malformed_or_cross_profile_strategy_checkpoint_fails(self):
        path = self.content("manthan")
        checkpoint = self.checkpoint(path)
        initial = json.loads(checkpoint.read_text())
        variants = [[], {**initial, "profile": "mustafa"}, {**initial, "idea": "Different idea"}, {**initial, "source": "different.md"}]
        bad_gate = copy.deepcopy(initial)
        bad_gate["gates"]["non_obvious"]["pass"] = "true"
        variants.append(bad_gate)
        for report in variants:
            with self.subTest(report=report):
                self.content("manthan")
                checkpoint.write_text(json.dumps(report))
                self.assert_failure(self.finalize(path, checkpoint), "STRATEGY_GATE_FAILED")
        self.content("manthan")
        self.assert_failure(self.finalize(path), "STRATEGY_GATE_FAILED")

    def test_embedded_checkpoint_rechecked_and_stale_strategy_revokes_approval(self):
        path = self.content("manthan")
        self.assertTrue(self.finalize(path, self.checkpoint(path), "approved")["valid"])
        self.assertTrue(self.finalize(path, status="approved")["valid"])
        strategy = self.root / "fixture-strategy.md"
        strategy.write_text(strategy.read_text() + "\nFixture-only strategy edit.\n")
        result = self.finalize(path, status="approved")
        self.assert_failure(result, "STRATEGY_GATE_FAILED")
        self.assertEqual(workflow.validator.read_document(path)["status"], "draft")
        self.assertIn("| status | draft |", path.with_suffix(".md").read_text())

    def test_failed_revalidation_revokes_previously_approved_output(self):
        self.complete_mustafa_fixture()
        path = self.content("mustafa")
        self.assertTrue(self.finalize(path, self.checkpoint(path), "approved")["valid"])
        content = workflow.validator.read_document(path)
        content["slides"][0]["claim_refs"] = ["fixture-unknown-claim"]
        self.write_yaml(path, content)
        result = self.finalize(path, status="approved")
        self.assert_failure(result, "UNKNOWN_CLAIM")
        self.assertIn("Validation: FAIL", path.with_suffix(".md").read_text())
        self.assertNotIn("| status | approved |", path.with_suffix(".md").read_text())

    def test_missing_identity_metadata_revokes_linked_approved_output(self):
        for field in ["content_id", "profile", "idea"]:
            with self.subTest(field=field):
                path = self.content("manthan")
                self.assertTrue(self.finalize(path, self.checkpoint(path), "approved")["valid"])
                content = workflow.validator.read_document(path)
                del content[field]
                self.write_yaml(path, content)
                result = self.finalize(path, status="approved")
                self.assert_failure(result, "INVALID_CAROUSEL_ARTIFACT")
                text = path.with_suffix(".md").read_text()
                self.assertIn("| status | draft |", text)
                self.assertIn("Validation: FAIL", text)
                self.assertNotIn("| status | approved |", text)

    def test_unparseable_or_wrong_root_source_revokes_linked_approved_output(self):
        for source in ["slides: [", "null\n", "[]\n"]:
            with self.subTest(source=source):
                path = self.content("manthan")
                self.assertTrue(self.finalize(path, self.checkpoint(path), "approved")["valid"])
                path.write_text(source)
                result = self.finalize(path, status="approved")
                self.assert_failure(result, "INVALID_CAROUSEL_ARTIFACT")
                text = path.with_suffix(".md").read_text()
                self.assertIn("| status | draft |", text)
                self.assertIn("Validation: FAIL", text)
                self.assertNotIn("| status | approved |", text)
                self.assertEqual(path.read_text(), source)

    def test_missing_carousel_metadata_blocks_approval(self):
        path = self.content("manthan")
        checkpoint = self.checkpoint(path)
        content = workflow.validator.read_document(path)
        del content["angle"]
        self.write_yaml(path, content)
        self.assert_failure(self.finalize(path, checkpoint, "approved"), "MISSING_REQUIRED_FIELD")

    def test_markdown_copy_is_derived_from_structured_source_and_notes_are_preserved(self):
        path = self.content("manthan")
        notes = self.root / "notes.md"
        notes.write_text("## Hook scores\n\nFixture scoring table.\n\n## Slide plan\n\nFixture plan.\n\n## Open questions\n\nFixture question.\n")
        self.assertTrue(self.finalize(path, self.checkpoint(path), notes=notes)["valid"])
        content = workflow.validator.read_document(path)
        content["slides"][2]["body"] = "Updated fixture copy from the canonical structured artifact."
        content["caption"] = "Updated fixture caption."
        self.write_yaml(path, content)
        self.assertTrue(self.finalize(path, status="draft")["valid"])
        text = path.with_suffix(".md").read_text()
        self.assertIn(content["slides"][2]["body"], text)
        self.assertIn(content["caption"], text)
        self.assertIn(notes.read_text(), text)

    def test_legacy_offer_and_calendar_metadata_survive_without_invented_offer_id(self):
        path = self.content("manthan")
        notes = self.root / "notes.md"
        notes.write_text("| Field | Value |\n| - | - |\n| calendar day | Fixture day |\n| design family | Fixture design |\n| offer | Fixture-only selected offer label |\n")
        result = self.finalize(path, self.checkpoint(path), notes=notes)
        self.assertTrue(result["valid"], result)
        self.assertNotIn("offer_id", workflow.validator.read_document(path))
        text = path.with_suffix(".md").read_text()
        self.assertIn(notes.read_text(), text)
        self.assertNotIn("| offer |  |", text)

    def test_existing_unmanaged_markdown_is_never_overwritten(self):
        path = self.content("manthan")
        checkpoint = self.checkpoint(path)
        markdown = path.with_suffix(".md")
        original = "# Existing user work\n\n| status | approved |\n"
        markdown.write_text(original)
        self.assert_failure(self.finalize(path, checkpoint), "INVALID_CAROUSEL_ARTIFACT")
        self.assertEqual(markdown.read_text(), original)

    def test_corrupt_embedded_checkpoint_preserves_build_notes_and_blocks_approval(self):
        path = self.content("manthan")
        notes = self.root / "notes.md"
        notes.write_text("## Open questions\n\nPreserve this fixture note.\n")
        self.assertTrue(self.finalize(path, self.checkpoint(path), "approved", notes)["valid"])
        markdown = path.with_suffix(".md")
        text = markdown.read_text().replace('"gates": {', '"gates": INVALID {', 1)
        markdown.write_text(text)
        result = self.finalize(path, status="approved")
        self.assert_failure(result, "INVALID_CAROUSEL_ARTIFACT")
        self.assertEqual(workflow.validator.read_document(path)["status"], "draft")
        self.assertIn(notes.read_text(), markdown.read_text())
        self.assertIn("Validation: FAIL", markdown.read_text())

    def test_markdown_write_failure_cannot_leave_approved_structured_state(self):
        path = self.content("manthan")
        checkpoint = self.checkpoint(path)
        original = Path.write_text
        failed = False
        def write(target, text, *args, **kwargs):
            nonlocal failed
            if target == path.with_suffix(".md") and not failed:
                failed = True
                raise OSError("Fixture-only write failure")
            return original(target, text, *args, **kwargs)
        with patch.object(Path, "write_text", write):
            result = self.finalize(path, checkpoint, "approved")
        self.assert_failure(result, "INVALID_CAROUSEL_ARTIFACT")
        self.assertEqual(workflow.validator.read_document(path)["status"], "draft")
        self.assertFalse(path.with_suffix(".md").exists())

    def test_incomplete_fixture_profile_cannot_finalize_or_approve(self):
        self.incomplete_mustafa_fixture()
        path = self.content("mustafa")
        with patch.object(workflow.validator, "validate_content", side_effect=AssertionError("Incomplete context must stop before validation")):
            result = self.finalize(path, status="approved")
        self.assert_failure(result, "INCOMPLETE_PROFILE")
        self.assertFalse(path.with_suffix(".md").exists())
        self.assertEqual(workflow.validator.read_document(path)["status"], "draft")

    def test_real_command_instructions_wire_strategy_generation_and_validation_in_order(self):
        command = (ROOT / ".claude/commands/carousel.md").read_text()
        self.assertLess(command.index("carousel_workflow.py gate"), command.index("## 4. Build"))
        self.assertLess(command.index("## 4. Build"), command.index("carousel_workflow.py finalize"))
        self.assertIn("--profile <id>", command)
        self.assertIn("scripts/validate_content.py", command)
        self.assertIn("zero automatic validation correction attempts", command)
        self.assertIn("public-facing validation must PASS", command)

    def test_prepare_cli_reports_default_pass_and_explicit_profile_blockers(self):
        self.incomplete_mustafa_fixture()
        runner = (
            "import sys; from pathlib import Path; from scripts import carousel_workflow as w; "
            "original=w.resolve_request; root=Path(sys.argv[1]); "
            "w.resolve_request=lambda raw, **kwargs: original(raw, root, **kwargs); "
            "sys.argv=[sys.argv[0], *sys.argv[2:]]; raise SystemExit(w.main())"
        )
        for arguments, success in [("A fixture idea.", True), ("--profile mustafa A fixture idea.", False)]:
            with self.subTest(arguments=arguments):
                result = subprocess.run([sys.executable, "-B", "-c", runner, str(self.root), "prepare", "--", arguments], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0 if success else 1, result.stderr)
                parsed = json.loads(result.stdout)
                self.assertEqual(parsed["valid"], success)
                self.assertEqual(parsed["profile"], "manthan" if success else "mustafa")

    def rejected_response(self, valid, verdict, errors=None):
        return {"valid": valid, "result": verdict, "errors": errors if errors is not None else [], "limitations": []}

    def assert_rejected_response(self, response):
        path = self.content("manthan")
        checkpoint = self.checkpoint(path)
        with patch.object(workflow.validator, "validate_content", return_value=response), patch.object(workflow, "markdown", wraps=workflow.markdown) as export:
            result = self.finalize(path, checkpoint, "public")
        self.assertFalse(result["valid"], result)
        self.assertEqual(result["result"], "FAIL")
        self.assertFalse(result["continue"])
        self.assertFalse(result["validation"]["valid"])
        self.assertEqual(result["validation"]["result"], "FAIL")
        self.assertTrue(result["errors"])
        self.assertEqual(export.call_count, 0)
        self.assertFalse(path.with_suffix(".md").exists())
        self.assertEqual(workflow.validator.read_document(path)["status"], "draft")
        self.assertEqual(workflow.validator.read_document(path.with_suffix(".validation-failure.json")), result)
        return path, checkpoint, result

    def test_fail_closed_false_valid_pass_verdict_empty_errors(self):
        self.assert_rejected_response(self.rejected_response(False, "PASS"))

    def test_fail_closed_true_valid_fail_verdict_empty_errors(self):
        self.assert_rejected_response(self.rejected_response(True, "FAIL"))

    def test_fail_closed_false_valid_fail_verdict_empty_errors(self):
        self.assert_rejected_response(self.rejected_response(False, "FAIL"))

    def test_fail_closed_error_list_prevents_export_and_continue_even_with_true_valid(self):
        error = {"code": "UNKNOWN_CLAIM", "message": "Fixture-only contradictory response."}
        for verdict in ["PASS", "FAIL"]:
            with self.subTest(verdict=verdict):
                _, _, result = self.assert_rejected_response(self.rejected_response(True, verdict, [error]))
                self.assertIn(error, result["errors"])

    def test_fail_closed_validation_failure_cannot_export_public_content(self):
        error = {"code": "UNKNOWN_CLAIM", "message": "Fixture-only missing claim."}
        _, _, result = self.assert_rejected_response(self.rejected_response(False, "FAIL", [error]))
        self.assertIn(error, result["errors"])

    def test_fail_closed_retry_preserves_failure_after_yaml_correction_in_same_run(self):
        path = self.content("manthan")
        checkpoint = self.checkpoint(path)
        content = workflow.validator.read_document(path)
        content["claims"] = ["fixture-unknown-claim"]
        self.write_yaml(path, content)
        first = self.finalize(path, checkpoint, "public")
        self.assert_failure(first, "UNKNOWN_CLAIM")
        content["claims"] = []
        self.write_yaml(path, content)
        with patch.object(workflow.validator, "validate_content", side_effect=AssertionError("A failed run must not validate again")), patch.object(workflow, "markdown", side_effect=AssertionError("A failed run must not export")):
            second = self.finalize(path, checkpoint, "public")
        self.assertEqual(second, first)
        self.assertFalse(path.with_suffix(".md").exists())

    def test_terminal_failure_is_bound_to_exact_artifact_identity(self):
        path = self.content("manthan")
        checkpoint = self.checkpoint(path)
        content = workflow.validator.read_document(path)
        content["claims"] = ["fixture-unknown-claim"]
        self.write_yaml(path, content)
        first = self.finalize(path, checkpoint, "public")
        self.assert_failure(first, "UNKNOWN_CLAIM")
        self.assertEqual(first["artifact_id"], path.stem)
        self.assertEqual(first["artifact_path"], str(path.relative_to(self.root)))
        failure = path.with_suffix(".validation-failure.json")
        state = workflow.validator.read_document(failure)
        state["artifact_id"] = "2099-01-01-other-artifact"
        failure.write_text(json.dumps(state))
        with patch.object(workflow.validator, "validate_content", side_effect=AssertionError("A mismatched terminal record must block before validation")):
            second = self.finalize(path, checkpoint, "public")
        self.assert_failure(second, "INVALID_WORKFLOW_STATE")
        self.assertEqual(workflow.validator.read_document(failure), state)

    def test_switching_filename_cannot_reuse_failed_content_identity(self):
        path = self.content("manthan")
        checkpoint = self.checkpoint(path)
        content = workflow.validator.read_document(path)
        content["claims"] = ["fixture-unknown-claim"]
        self.write_yaml(path, content)
        first = self.finalize(path, checkpoint, "public")
        self.assert_failure(first, "UNKNOWN_CLAIM")
        renamed = self.root / "content/carousels/2099-01-01-renamed-fixture.yaml"
        renamed.write_bytes(path.read_bytes())
        with patch.object(workflow.validator, "validate_content", side_effect=AssertionError("A renamed failed identity must not reach validation")):
            second = self.finalize(renamed, checkpoint, "public")
        self.assert_failure(second, "INVALID_CAROUSEL_ARTIFACT")
        self.assertEqual(workflow.validator.read_document(renamed)["content_id"], path.stem)
        self.assertFalse(renamed.with_suffix(".md").exists())

    def test_new_intentional_artifact_uses_a_new_identity_after_failure(self):
        path = self.content("manthan")
        checkpoint = self.checkpoint(path)
        content = workflow.validator.read_document(path)
        content["claims"] = ["fixture-unknown-claim"]
        self.write_yaml(path, content)
        self.assert_failure(self.finalize(path, checkpoint, "public"), "UNKNOWN_CLAIM")
        new_path = self.root / "content/carousels/2099-01-01-new-fixture-run.yaml"
        content["content_id"] = new_path.stem
        content["claims"] = []
        self.write_yaml(new_path, content)
        result = self.finalize(new_path, checkpoint, "draft")
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["artifact_id"], new_path.stem)
        self.assertTrue(new_path.with_suffix(".md").exists())

    def test_terminal_journal_survives_failure_record_deletion_and_pass_restoration(self):
        path = self.content("manthan")
        checkpoint = self.checkpoint(path)
        content = workflow.validator.read_document(path)
        content["claims"] = ["fixture-unknown-claim"]
        self.write_yaml(path, content)
        first = self.finalize(path, checkpoint, "public")
        self.assert_failure(first, "UNKNOWN_CLAIM")
        path.with_suffix(".validation-failure.json").unlink()
        path.with_suffix(".md").write_text(f"| status | approved |\n\n<!-- structured-content: {path.name} -->\nValidation: PASS\n")
        content["claims"] = []
        self.write_yaml(path, content)
        with patch.object(workflow.validator, "validate_content", side_effect=AssertionError("A terminal journal must block retry")):
            second = self.finalize(path, checkpoint, "public")
        self.assertEqual(second, first)
        self.assertEqual(workflow.validator.read_document(path)["status"], "draft")
        self.assertIn("Validation: FAIL", path.with_suffix(".md").read_text())

    def test_interrupted_running_state_is_recovered_as_terminal_failure(self):
        path = self.content("manthan")
        checkpoint = self.checkpoint(path)
        self.assertTrue(self.finalize(path, checkpoint, "approved")["valid"])
        state = path.parent / ".workflow-state" / f"{path.stem}.json"
        artifact_state.atomic_json(state, {**artifact_state.binding(path, self.root), "state": "RUNNING", "result": None})
        with patch.object(workflow.validator, "validate_content", side_effect=AssertionError("Interrupted artifacts must not revalidate")):
            result = self.finalize(path, checkpoint, "approved")
        self.assert_failure(result, "INVALID_WORKFLOW_STATE")
        self.assertEqual(workflow.validator.read_document(path)["status"], "draft")
        self.assertIn("Validation: FAIL", path.with_suffix(".md").read_text())
        journal = workflow.validator.read_document(state)
        self.assertEqual(journal["state"], "FAIL")
        self.assertEqual(journal["result"], result)

    def test_export_boundary_blocks_authoritative_input_change_after_validation(self):
        self.complete_mustafa_fixture()
        path = self.content("mustafa")
        checkpoint = self.checkpoint(path)
        original = workflow.validator.validate_content

        def validate_then_change(*args, **kwargs):
            result = original(*args, **kwargs)
            claims_path = self.root / "knowledge/claims.yaml"
            claims = workflow.validator.read_document(claims_path)
            claims["claims"][0]["claim"] += " Fixture-only post-validation mutation."
            self.write_yaml(claims_path, claims)
            return result

        with patch.object(workflow.validator, "validate_content", side_effect=validate_then_change), patch.object(workflow, "markdown") as export:
            result = self.finalize(path, checkpoint, "public")
        self.assert_failure(result, "VALIDATION_INPUT_CHANGED")
        self.assertEqual(result["phase"], "validation_state")
        self.assertEqual(result["validation_inputs"]["status"], "CHANGED")
        self.assertFalse(result["continue"])
        export.assert_not_called()
        self.assertFalse(path.with_suffix(".md").exists())
        self.assertEqual(workflow.validator.read_document(path)["status"], "draft")
        self.assertEqual(workflow.validator.read_document(path.with_suffix(".validation-failure.json")), result)

    def test_fail_closed_retry_cannot_switch_failed_public_run_to_internal_draft(self):
        self.complete_mustafa_fixture()
        path = self.content("mustafa")
        checkpoint = self.checkpoint(path)
        claims_path = self.root / "knowledge/claims.yaml"
        claims = workflow.validator.read_document(claims_path)
        claims["claims"][0]["public_use"] = "private"
        self.write_yaml(claims_path, claims)
        first = self.finalize(path, checkpoint, "approved")
        self.assert_failure(first, "RESTRICTED_CLAIM")
        with patch.object(workflow.validator, "validate_content", side_effect=AssertionError("Draft mode must not reset a failed run")):
            second = self.finalize(path, checkpoint)
        self.assertEqual(second, first)
        self.assertTrue(second["validation"]["public_facing"])

    def test_fail_closed_conflicting_pass_notes_cannot_override_authoritative_failure(self):
        path = self.content("manthan")
        checkpoint = self.checkpoint(path)
        notes = self.root / "notes.md"
        notes.write_text("Validation: PASS\nA note is not a controller verdict.\n")
        response = self.rejected_response(False, "FAIL", [{"code": "UNKNOWN_CLAIM", "message": "Fixture rejection."}])
        with patch.object(workflow.validator, "validate_content", return_value=response):
            result = self.finalize(path, checkpoint, "public", notes)
        self.assert_failure(result, "UNKNOWN_CLAIM")
        self.assertEqual(result["validation"]["result"], "FAIL")
        self.assertFalse(path.with_suffix(".md").exists())
        self.assertEqual(workflow.validator.read_document(path.with_suffix(".validation-failure.json")), result)

    def test_fail_closed_linked_markdown_has_only_failed_verdict_after_rejection(self):
        path = self.content("manthan")
        checkpoint = self.checkpoint(path)
        notes = self.root / "notes.md"
        notes.write_text("Validation: PASS\n- Prior note: Validation: PASS (not authoritative)\n")
        self.assertTrue(self.finalize(path, checkpoint, "approved", notes)["valid"])
        with patch.object(workflow.validator, "validate_content", return_value=self.rejected_response(False, "FAIL")), patch.object(workflow, "markdown", wraps=workflow.markdown) as export:
            result = self.finalize(path, status="public")
        self.assertFalse(result["continue"])
        self.assertEqual(export.call_count, 0)
        text = path.with_suffix(".md").read_text()
        self.assertIn("Validation: FAIL", text)
        self.assertNotIn("Validation: PASS", text)
        self.assertNotIn("| status | approved |", text)

    def test_fail_closed_write_exception_preserves_failed_verdict_and_blocks_retry(self):
        path = self.content("manthan")
        checkpoint = self.checkpoint(path)
        original = Path.write_text
        def write(target, text, *args, **kwargs):
            if target == path.with_suffix(".md"):
                raise OSError("Fixture-only export failure")
            return original(target, text, *args, **kwargs)
        with patch.object(Path, "write_text", write):
            first = self.finalize(path, checkpoint, "approved")
        self.assert_failure(first, "INVALID_CAROUSEL_ARTIFACT")
        self.assertEqual(first["validation"]["result"], "FAIL")
        self.assertFalse(first["validation"]["valid"])
        with patch.object(workflow.validator, "validate_content", side_effect=AssertionError("An export failure must terminate the run")):
            second = self.finalize(path, checkpoint, "approved")
        self.assertEqual(second, first)

    def test_fail_closed_partial_export_is_removed_after_write_exception(self):
        path = self.content("manthan")
        checkpoint = self.checkpoint(path)
        original = Path.write_text
        def write(target, text, *args, **kwargs):
            if target == path.with_suffix(".md"):
                original(target, text.split("## Slides", 1)[0], *args, **kwargs)
                raise OSError("Fixture-only partial export failure")
            return original(target, text, *args, **kwargs)
        with patch.object(Path, "write_text", write):
            result = self.finalize(path, checkpoint, "public")
        self.assert_failure(result, "INVALID_CAROUSEL_ARTIFACT")
        self.assertEqual(result["validation"]["result"], "FAIL")
        self.assertNotIn("files", result)
        self.assertFalse(path.with_suffix(".md").exists())
        self.assertEqual(workflow.validator.read_document(path)["status"], "draft")
        self.assertEqual(workflow.validator.read_document(path.with_suffix(".validation-failure.json")), result)

    def test_fail_closed_source_write_failure_still_revokes_linked_markdown(self):
        path = self.content("manthan")
        checkpoint = self.checkpoint(path)
        notes = self.root / "notes.md"
        notes.write_text("Validation: PASS\nPreserve this fixture note.\n")
        self.assertTrue(self.finalize(path, checkpoint, "approved", notes)["valid"])
        content = workflow.validator.read_document(path)
        content["claims"] = ["fixture-unknown-claim"]
        self.write_yaml(path, content)
        original = Path.write_text
        def write(target, text, *args, **kwargs):
            if target == path:
                raise OSError("Fixture-only source state write failure")
            return original(target, text, *args, **kwargs)
        with patch.object(Path, "write_text", write):
            result = self.finalize(path, status="public")
        self.assert_failure(result, "UNKNOWN_CLAIM")
        self.assert_failure(result, "INVALID_CAROUSEL_ARTIFACT")
        text = path.with_suffix(".md").read_text()
        self.assertIn("Validation: FAIL", text)
        self.assertNotIn("Validation: PASS", text)
        self.assertIn("| status | draft |", text)
        self.assertIn("Preserve this fixture note.", text)
        self.assertEqual(workflow.validator.read_document(path.with_suffix(".validation-failure.json")), result)

    def test_fail_closed_corrupt_terminal_record_cannot_reset_the_run(self):
        for state in ["{", "[]", json.dumps({"valid": True, "result": "PASS", "continue": True, "errors": []})]:
            with self.subTest(state=state):
                path = self.content("manthan")
                checkpoint = self.checkpoint(path)
                failure = path.with_suffix(".validation-failure.json")
                failure.write_text(state)
                with patch.object(workflow.validator, "validate_content") as validate:
                    result = self.finalize(path, checkpoint, "public")
                validate.assert_not_called()
                self.assertFalse(result["valid"], result)
                self.assertEqual(result["result"], "FAIL")
                self.assertFalse(result["continue"])
                self.assertFalse(path.with_suffix(".md").exists())
                self.assertEqual(failure.read_text(), state)

    def test_fail_closed_malformed_responses_are_rejected(self):
        for response in [None, {}, [], {"valid": True, "result": "PASS"}, {"valid": 1, "result": "PASS", "errors": []}, {"valid": "true", "result": "PASS", "errors": []}, {"valid": True, "result": "PASS", "errors": None}]:
            with self.subTest(response=response):
                self.assert_rejected_response(response)

    def test_fail_closed_validator_exception_is_terminal(self):
        path = self.content("manthan")
        checkpoint = self.checkpoint(path)
        with patch.object(workflow.validator, "validate_content", side_effect=RuntimeError("Fixture-only validator exception")):
            result = self.finalize(path, checkpoint, "public")
        self.assertFalse(result["continue"])
        self.assertEqual(result["result"], "FAIL")
        self.assertFalse(path.with_suffix(".md").exists())
        self.assertEqual(workflow.validator.read_document(path.with_suffix(".validation-failure.json")), result)

    def test_fail_closed_terminal_state_blocks_retry_across_cli_processes(self):
        path = self.content("manthan")
        checkpoint = self.checkpoint(path)
        content = workflow.validator.read_document(path)
        content["claims"] = ["fixture-unknown-claim"]
        self.write_yaml(path, content)
        runner = (
            "import sys; from pathlib import Path; from scripts import carousel_workflow as w; "
            "original=w.finalize_carousel; root=Path(sys.argv[1]); "
            "w.finalize_carousel=lambda *args, **kwargs: original(*args, **kwargs, repository_root=root); "
            "sys.argv=[sys.argv[0], *sys.argv[2:]]; raise SystemExit(w.main())"
        )
        args = [sys.executable, "-B", "-c", runner, str(self.root), "finalize", str(path), "--strategy", str(checkpoint), "--status", "public"]
        first = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(first.returncode, 1, first.stderr)
        content["claims"] = []
        self.write_yaml(path, content)
        second = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(second.returncode, 1, second.stderr)
        self.assertEqual(json.loads(second.stdout), json.loads(first.stdout))
        self.assertFalse(path.with_suffix(".md").exists())

    def test_fail_closed_authoritative_pass_preserves_valid_export_behavior(self):
        path = self.content("manthan")
        checkpoint = self.checkpoint(path)
        with patch.object(workflow.validator, "validate_content", return_value={"valid": True, "result": "PASS", "errors": []}):
            result = self.finalize(path, checkpoint, "approved")
        self.assertTrue(result["valid"], result)
        self.assertTrue(result["continue"])
        self.assertEqual(workflow.validator.read_document(path)["status"], "approved")
        self.assertTrue(path.with_suffix(".md").exists())
        self.assertFalse(path.with_suffix(".validation-failure.json").exists())

    def test_existing_examples_and_real_authority_files_are_not_modified(self):
        paths = [PUBLIC_FIXTURE_ROOT / "repository/profiles/active.yaml", PUBLIC_FIXTURE_ROOT / "knowledge/claims.yaml", PUBLIC_FIXTURE_ROOT / "knowledge/evidence.yaml"]
        before = [path.read_bytes() for path in paths]
        content = self.content("manthan")
        self.assertTrue(self.finalize(content, self.checkpoint(content))["valid"])
        self.assertEqual([path.read_bytes() for path in paths], before)


if __name__ == "__main__":
    unittest.main()
