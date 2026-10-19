"""Profile resolution, strategy checkpoint, and validation gate for /carousel."""

import argparse
import copy
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

import yaml
from jsonschema.exceptions import SchemaError

if __package__:
    from . import artifact_state
    from . import validate_content as validator
    from .validate_claim_registry import UniqueSafeLoader, unique_json
else:
    import artifact_state
    import validate_content as validator
    from validate_claim_registry import UniqueSafeLoader, unique_json


ROOT = validator.ROOT
GATES = ("non_obvious", "one_of_none", "highly_tactical")
REQUIRED_CONTENT = (
    "content_id", "profile", "status", "platform", "content_type", "pillar",
    "angle", "hook", "slides", "caption", "cta", "claims", "idea",
)
SYSTEM_SOURCES = (
    "systems/brand-voice.md", "systems/carousel-design-system.md",
    "systems/carousel-types.md", "systems/hook-rubric-20pt.md",
)
STRATEGY_START = "<!-- strategy-checkpoint -->\n```json\n"
STRATEGY_END = "\n```\n<!-- /strategy-checkpoint -->"
NOTES_START = "<!-- build-notes -->\n"
NOTES_END = "\n<!-- /build-notes -->"
DRAFT_SOURCES = ("identity", "voice", "strategy", "design_system")
READY_STATUSES = ("active", "verified", "ready", "configured")
UNRESOLVED = re.compile(r"\b(?:TODO[_ -]*VERIFY|unresolved|incomplete|placeholder|TBD|TBC|unknown)\b|<[^>]+>", re.IGNORECASE)
# This is a required-field contract, not a scan of every creator-data leaf.
DRAFT_FIELDS = {
    "identity": ("identity.name", "professional_positioning.primary_title", "professional_positioning.positioning_statement"),
    "voice": ("tone", "writing_rules"),
}
CTA_FIELDS = ("primary_mechanic", "keyword", "delivery_asset", "destination_url", "offer_selection", "conversion_path")


def fail(result, code, message):
    result["errors"].append({"code": code, "message": message})


def authoritative_pass(response):
    """Trust only an explicit, internally consistent validator decision."""
    return (
        isinstance(response, dict)
        and response.get("valid") is True
        and response.get("result") == "PASS"
        and isinstance(response.get("errors"), list)
        and not response["errors"]
        and response.get("continue", True) is True
    )


def validation_decision(response):
    """Preserve diagnostics, but never promote an inconsistent response to PASS."""
    decision = copy.deepcopy(response) if isinstance(response, dict) else {}
    if authoritative_pass(decision):
        return decision
    errors = decision.get("errors")
    errors = [
        error for error in errors
        if isinstance(error, dict) and isinstance(error.get("code"), str)
        and isinstance(error.get("message"), str)
    ] if isinstance(errors, list) else []
    if not errors:
        errors = [{
            "code": "INVALID_VALIDATION_RESULT",
            "message": "Validator must return valid=true, result=PASS, and an empty error list to permit continuation",
        }]
    decision.update({"valid": False, "result": "FAIL", "continue": False, "errors": errors})
    return decision


def finish(result):
    result["valid"] = not result["errors"]
    result["result"] = "PASS" if result["valid"] else "FAIL"
    if not result["valid"] and "continue" in result:
        result["continue"] = False
        result.pop("files", None)
    return result


def scoped_path(root, value):
    path = (root / value).resolve()
    path.relative_to(root.resolve())
    return path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_path(root, path):
    """Return a stable repository-relative path for machine-readable reports."""
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(Path(root).resolve()))
    except ValueError:
        return str(resolved)


def validation_input_paths(root, context, claims_path, evidence_path, content_path):
    """List authoritative files that must remain stable through validation/export."""
    paths = [
        Path(content_path),
        root / "profiles/active.yaml",
        root / context["manifest"],
        validator.DEFAULT_SCHEMA,
        validator.CLAIM_SCHEMA,
        validator.EVIDENCE_SCHEMA,
        ROOT / "schemas/active-profile.schema.json",
        ROOT / "schemas/creator-profile.schema.json",
    ]
    if context["mode"] != "legacy-reference":
        paths.extend((Path(claims_path), Path(evidence_path)))
        evidence = validator.read_document(evidence_path)
        for record in evidence.get("evidence", []) if isinstance(evidence, dict) else []:
            if isinstance(record, dict) and isinstance(record.get("locator"), dict):
                locator = record["locator"].get("path")
                if isinstance(locator, str):
                    paths.append(scoped_path(root, locator))
    paths.extend(root / source for source in context.get("sources", {}).values())
    paths.extend(root / source for source in context.get("system_sources", ()))
    unique = {}
    for path in paths:
        resolved = Path(path).resolve()
        unique[relative_path(root, resolved)] = resolved
    return [unique[name] for name in sorted(unique)]


def fingerprint_validation_inputs(root, paths):
    """Fingerprint authoritative inputs without changing them."""
    return {relative_path(root, path): sha256(path) if path.is_file() else None for path in paths}


def resolved_text(value):
    return isinstance(value, str) and bool(value.strip()) and not UNRESOLVED.search(value) and value.strip().lower() not in {"none", "null", "n/a", "unavailable"}


def resolved_texts(value):
    return isinstance(value, list) and bool(value) and all(resolved_text(item) for item in value)


def resolved_destination(value):
    if not resolved_text(value) or any(character.isspace() for character in value):
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname)
    except ValueError:
        return False


def field_value(document, selector):
    for key in selector.split("."):
        document = document.get(key) if isinstance(document, dict) else None
    return document


def profile_document(path):
    if path.suffix != ".md":
        data = validator.read_document(path)
    else:
        match = re.match(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", path.read_text(), re.DOTALL)
        if not match:
            raise ValueError("Required machine-readable YAML front matter is missing")
        data = yaml.load(match.group(1), Loader=UniqueSafeLoader)
    if not isinstance(data, dict):
        raise ValueError("Required configuration must be an object")
    return data


def markdown_section(text, heading):
    match = re.search(r"(?m)^## " + re.escape(heading) + r"[ \t]*\n", text)
    return re.split(r"(?m)^## ", text[match.end():], maxsplit=1)[0].strip() if match else ""


def check_readiness(context, repository_root=ROOT, mode="draft", platform="instagram", pillar=None, content=None):
    """Read required configuration only. Do not infer values or inspect prose claims."""
    root = Path(repository_root).resolve()
    profile = context.get("profile")
    public = mode in validator.PUBLIC_MODES
    result = {"profile": profile, "mode": mode, "platform": platform, "phase": "readiness", "sources": {}, "checks": [], "errors": [], "continue": False}

    def check(name, path, passed, requirement, scope="draft"):
        passed = bool(passed)
        result["checks"].append({"profile": profile, "check": name, "path": path, "scope": scope,
                                 "status": "PASS" if passed else "FAIL", "reason": ("Configured: " if passed else "Required: ") + requirement,
                                 "blocking": not passed and (scope == "draft" or public)})

    def load(key, scope="draft", structured=True):
        value = manifest.get("files" if structured else "legacy_sources", {}).get(key)
        location = f"{context.get('manifest', 'profile.yaml')}#files.{key}"
        try:
            if not resolved_text(value):
                raise ValueError("Declare a resolved source path")
            path = scoped_path(root, str(manifest_path.parent.relative_to(root) / value) if structured else value)
            location = str(path.relative_to(root))
            result["sources"][key] = location
            data = profile_document(path) if structured else path.read_text()
            check("profile.source", location, True, f"Readable {key} source", scope)
            if structured:
                check("profile.scope", location + "#profile_id", data.get("profile_id") == profile, "Source profile_id must match selected profile", scope)
            return data, location
        except (OSError, ValueError, yaml.YAMLError) as error:
            check("profile.source", location, False, str(error), scope)
            return {} if structured else "", location

    def required(document, source, selector, predicate=resolved_text, scope="draft", name="profile.required"):
        value = field_value(document, selector)
        check(name, source + "#" + selector, predicate(value), f"Resolve {selector} with the required type and authorization", scope)
        return value

    try:
        check("readiness.mode", "mode", mode in validator.MODES, "Use draft/review or approved/public readiness")
        check("channel.selection", "platform", resolved_text(platform), "Select an explicit publishing platform", "public")
        base_errors = [error for error in context.get("errors", []) if error["code"] != "READINESS_BLOCKED"]
        check("profile.context", "profile", not base_errors, "Profile/schema/source resolution must pass")
        manifest_path = scoped_path(root, context["manifest"])
        manifest = profile_document(manifest_path)
        manifest_source = str(manifest_path.relative_to(root))
        check("profile.selection", manifest_source + "#profile_id", manifest.get("profile_id") == profile, "Manifest must match the explicitly selected profile")
        check("profile.status", manifest_source + "#status", manifest.get("status") in {"active", "draft"}, "Profile status must permit drafting (active or draft)")
        check("profile.public_status", manifest_source + "#status", manifest.get("status") == "active", "Public readiness requires an explicitly active profile", "public")
        if manifest.get("mode") == "legacy-reference":
            # Explicit compatibility contract for the established root Markdown format.
            identity, identity_source = load("identity", structured=False)
            voice, voice_source = load("voice", structured=False)
            strategy, strategy_source = load("strategy", structured=False)
            channels, channel_source = load("channels", "public", structured=False)
            offers, offer_source = load("offers", "cta", structured=False)
            current, current_source = load("current_data", "cta", structured=False)
            check("profile.identity", identity_source + "#Who I am", bool(markdown_section(identity, "Who I am")), "Explicit creator identity section")
            check("profile.voice", voice_source + "#Core rules", bool(markdown_section(voice, "Core rules")), "Declared voice rules")
            rules = markdown_section(strategy, "Net new value filter (mandatory)")
            for gate, label in zip(GATES, ("Non-obvious", "One of none", "Highly tactical")):
                rule = re.search(r"(?m)^- \*\*" + re.escape(label) + r"\.\*\* (.+)$", rules)
                check("strategy.novelty_rules", strategy_source + "#" + gate, bool(rule and resolved_text(rule.group(1))), "Explicit legacy " + gate + " rule")
            check("strategy.active_pillars", strategy_source + "#Content pillars", bool(markdown_section(strategy, "Content pillars")), "Declared legacy content pillars")
            rows = [line.split("|")[1:-1] for line in channels.splitlines() if line.startswith("|")]
            selected = [row for row in rows if len(row) >= 2 and row[0].strip().lower() == str(platform).lower()]
            check("channel.identity", channel_source + "#" + str(platform), len(selected) == 1 and resolved_text(selected[0][1].strip()), "Explicit account identifier for selected legacy platform", "public")
            mechanic = markdown_section(offers, "The CTA mechanic")
            catalog = re.search(r"(?m)^## Offer 1: .+\n", offers)
            catalog = re.split(r"(?m)^## ", offers[catalog.end():], maxsplit=1)[0] if catalog else ""
            destination = re.search(r"(?m)^\| Link \| (https?://[^ |]+) \|", catalog)
            keywords = markdown_section(current, "CTA keywords in rotation")
            keyword_rows = re.findall(r'(?m)^\| ["“]([^"”]+)["”] \|', keywords)
            check("cta.primary_mechanic", offer_source + "#The CTA mechanic", bool(mechanic and "- Format:" in mechanic), "Explicit legacy CTA mechanic", "cta")
            check("cta.keyword", current_source + "#CTA keywords in rotation", bool(keyword_rows) and all(resolved_text(word) for word in keyword_rows), "Explicit legacy keyword inventory", "cta")
            check("cta.offer", offer_source + "#Offer 1", bool(catalog and "| Price |" in catalog), "Declared legacy primary offer", "cta")
            check("cta.destination_url", offer_source + "#Offer 1.Link", bool(destination and resolved_text(destination.group(1))), "Explicit legacy offer destination", "cta")
            check("cta.delivery_asset", offer_source + "#The CTA mechanic", bool(re.search(r"(?m)^- The reason is always value: .+", mechanic)), "Declared legacy delivery/value policy", "cta")
        else:
            check("profile.mode", manifest_source + "#mode", manifest.get("mode") == "structured", "Supported profile mode")
            documents = {key: load(key) for key in DRAFT_FIELDS}
            for key, selectors in DRAFT_FIELDS.items():
                document, source = documents[key]
                for selector in selectors:
                    required(document, source, selector, resolved_texts if key == "voice" else resolved_text)
            identity, identity_source = documents["identity"]
            for selector in ("identity.status", "professional_positioning.status"):
                required(identity, identity_source, selector, lambda value: isinstance(value, str) and value in READY_STATUSES)
            for selector in ("identity.public_use", "professional_positioning.public_use"):
                required(identity, identity_source, selector, lambda value: value == "public", "public")
            voice, voice_source = documents["voice"]
            required(voice, voice_source, "specification_status", lambda value: isinstance(value, str) and value in READY_STATUSES)
            strategy, strategy_source = load("strategy")
            for selector in ("status", "active_selection_status", "novelty_gate.status"):
                required(strategy, strategy_source, selector, lambda value: isinstance(value, str) and value in READY_STATUSES, name="strategy.status")
            rules = required(strategy, strategy_source, "novelty_gate.configured_rules", lambda value: isinstance(value, dict) and bool(value), name="strategy.novelty_rules")
            for gate in GATES:
                rule = rules.get(gate) if isinstance(rules, dict) else None
                check("strategy.novelty_rules", strategy_source + "#novelty_gate.configured_rules." + gate, resolved_text(rule) or resolved_texts(rule), "Configure an explicit " + gate + " rule")
            active_ids = required(strategy, strategy_source, "active_pillar_ids", resolved_texts, name="strategy.active_pillars")
            pillars = strategy.get("pillars", [])
            active_records = []
            for identifier in active_ids if resolved_texts(active_ids) else []:
                records = [item for item in pillars if isinstance(item, dict) and item.get("id") == identifier] if isinstance(pillars, list) else []
                check("strategy.active_pillars", strategy_source + "#pillars[" + identifier + "]", len(records) == 1, "Active pillar ID must identify exactly one configured record")
                record = records[0] if len(records) == 1 else {}
                for field in ("name", "status"):
                    passed = resolved_text(record.get(field)) if field == "name" else record.get(field) in ("active", "verified")
                    check("strategy.active_pillars", strategy_source + "#pillars[" + identifier + "]." + field, passed, "Active pillar needs a resolved name and active/verified status")
                active_records.append(record)
            if pillar is not None or content is not None:
                check("strategy.pillar_selection", "content.pillar", resolved_text(pillar) and any(pillar in (record.get("id"), record.get("name")) for record in active_records), "Select a configured active pillar ID or exact name")
            channels, channel_source = load("channels", "public")
            records = channels.get("channels", [])
            selected = [item for item in records if isinstance(item, dict) and item.get("id") == platform] if isinstance(records, list) else []
            check("channel.selection", channel_source + "#channels[" + str(platform) + "]", len(selected) == 1, "Configure exactly one selected channel; no fallback account", "public")
            channel = selected[0] if len(selected) == 1 else {}
            for field, predicate in (("handle_or_url", resolved_text),
                                     ("content_types", lambda value: resolved_texts(value) and any(item.lower() in {"carousel", "carousels"} for item in value)),
                                     ("status", lambda value: isinstance(value, str) and value in READY_STATUSES),
                                     ("publishable", lambda value: value is True), ("public_use", lambda value: value == "public"),
                                     ("verification_status", lambda value: value == "verified")):
                requirement = "Resolve and authorize selected channel " + field
                if field == "content_types":
                    requirement = "Configure a resolved content_types list that explicitly includes carousel or carousels"
                if field == "handle_or_url" and channel.get(field) == "unavailable":
                    requirement = "Configure an available account; this channel is explicitly unavailable and allows private drafting only"
                check("channel.configuration", channel_source + "#channels[" + str(platform) + "]." + field, predicate(channel.get(field)), requirement, "public")
            offers, offer_source = load("offers", "cta")
            policy = offers.get("cta_policy", {})
            for field in CTA_FIELDS:
                required(offers, offer_source, "cta_policy." + field, resolved_destination if field == "destination_url" else validator.resolved_cta_value, scope="cta", name="cta." + field)
            for field in ("enabled", "publishable", "status"):
                if isinstance(policy, dict) and field in policy:
                    passed = policy[field] in READY_STATUSES if field == "status" else policy[field] is True
                    check("cta.policy_" + field, offer_source + "#cta_policy." + field, passed, "Explicit CTA policy status/flags must permit use", "cta")
            permission = policy.get("public_use", offers.get("public_use")) if isinstance(policy, dict) else None
            check("cta.permission", offer_source + "#cta_policy.public_use", permission == "public", "CTA policy must explicitly permit public use (local or inherited)", "cta")
            offer_id = policy.get("offer_selection") if isinstance(policy, dict) else None
            records = offers.get("offers", [])
            selected = [item for item in records if isinstance(item, dict) and item.get("id") == offer_id] if isinstance(records, list) and resolved_text(offer_id) else []
            check("cta.offer_selection", offer_source + "#cta_policy.offer_selection", len(selected) == 1, "Select exactly one explicitly configured offer", "cta")
            offer = selected[0] if len(selected) == 1 else {}
            for field in ("name", "description", "target_customer", "status", "publishable", "public_use"):
                value = offer.get(field, offers.get("public_use") if field == "public_use" else None)
                passed = value is True if field == "publishable" else (value == "public" if field == "public_use" else (isinstance(value, str) and value in READY_STATUSES if field == "status" else resolved_text(value)))
                check("cta.offer", offer_source + "#offers[" + str(offer_id) + "]." + field, passed, "Resolve and authorize selected offer " + field, "cta")
            for record, source, scope in ((offer, offer_source, "cta"), (channel, channel_source, "public")):
                if "enabled" in record:
                    check(scope + ".enabled", source + "#enabled", record["enabled"] is True, "Explicit selected-record enabled flag must be true", scope)
            if isinstance(content, dict):
                for field, configured in (("keyword", field_value(offers, "cta_policy.keyword")), ("offer_id", offer_id)):
                    if field in content:
                        check("cta.selection", "content." + field, resolved_text(content[field]) and content[field] == configured, "Explicit CTA metadata must match configured policy", "cta")
                slides = content.get("slides", [])
                cta_used = bool(content.get("cta") or content.get("keyword") or content.get("offer_id")) or "cta_mechanics" in content
                if isinstance(slides, list):
                    cta_used = cta_used or any(
                        isinstance(slide, dict) and slide.get("role") == "cta" and (slide.get("body") or slide.get("headline"))
                        for slide in slides
                    )
                if cta_used:
                    cta_ready = all(row["status"] == "PASS" for row in result["checks"] if row["scope"] == "cta")
                    check("cta.generation", "content.cta", cta_ready, "Omit CTA copy/metadata while CTA configuration is unresolved; private body drafting remains allowed")
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as error:
        check("profile.configuration", context.get("manifest", "profile"), False, str(error))
    result["draft_ready"] = all(row["status"] == "PASS" for row in result["checks"] if row["scope"] == "draft")
    result["cta_ready"] = any(row["scope"] == "cta" for row in result["checks"]) and all(row["status"] == "PASS" for row in result["checks"] if row["scope"] == "cta")
    result["public_ready"] = result["draft_ready"] and all(row["status"] == "PASS" for row in result["checks"])
    result["errors"] = [{"code": "READINESS_BLOCKED", "path": row["path"], "message": row["reason"]} for row in result["checks"] if row["blocking"]]
    finish(result)
    result["continue"] = result["valid"]
    return result


def apply_readiness(result, report):
    result["readiness"] = report
    if report["errors"]:
        result["phase"] = "readiness"
    for error in report["errors"]:
        if error not in result["errors"]:
            result["errors"].append(error)


def resolve_request(arguments, repository_root=ROOT, mode="draft", platform="instagram", pillar=None):
    """Resolve a per-run selection, never changing the active-profile file."""
    root = Path(repository_root).resolve()
    result = {"profile": None, "idea": None, "mode": None, "sources": {}, "errors": [], "continue": False}
    raw = arguments.strip()
    override = None
    if raw.startswith("--"):
        match = re.fullmatch(r"--profile\s+([a-z0-9][a-z0-9-]*)(?:\s+(.*))?", raw, re.DOTALL)
        if not match:
            fail(result, "INVALID_ARGUMENTS", "Use /carousel [--profile <id>] <idea>; only a leading --profile is supported")
            return finish(result)
        override, raw = match.group(1), (match.group(2) or "").strip()
    if not raw:
        fail(result, "MISSING_IDEA", "Supply one core idea; no topic is inferred")
        return finish(result)
    result["idea"] = raw
    try:
        active = validator.read_document(root / "profiles/active.yaml")
        validator.schema_errors(result, active, ROOT / "schemas/active-profile.schema.json", "active_profile", "INVALID_PROFILE")
        if result["errors"]:
            return finish(result)
        selected = override or active["active_profile"]
        result["profile"] = selected
        result["active_profile"] = active["active_profile"]
        entry = next((item for item in active["profiles"] if item["profile_id"] == selected), None)
        if entry is None:
            fail(result, "UNKNOWN_PROFILE", f"Profile {selected!r} is not declared in profiles/active.yaml")
            return finish(result)
        manifest_path = scoped_path(root, entry["manifest"])
        manifest = validator.read_document(manifest_path)
        validator.schema_errors(result, manifest, ROOT / "schemas/creator-profile.schema.json", "profile", "INVALID_PROFILE")
        if result["errors"]:
            return finish(result)
        result["mode"] = manifest["mode"]
        result["manifest"] = str(manifest_path.relative_to(root))
        if manifest["profile_id"] != selected:
            fail(result, "PROFILE_MISMATCH", "Selected profile and manifest profile_id must agree")
        structured = manifest["mode"] == "structured"
        if structured and manifest.get("status") == "incomplete":
            fail(result, "INCOMPLETE_PROFILE", f"Selected profile {selected!r} is incomplete; stop before generation")
        sources = manifest.get("files" if structured else "legacy_sources", {})
        required_sources = DRAFT_SOURCES if structured else ("identity", "offers", "voice", "channels", "strategy", "design_system")
        for key in required_sources:
            if key not in sources:
                fail(result, "MISSING_PROFILE_SOURCE", f"Missing declared source: {key}")
        for key, value in sources.items():
            if not resolved_text(value):
                if key in required_sources:
                    fail(result, "UNRESOLVED_PROFILE_SOURCE", f"files.{key}: unresolved; this path is not read")
                continue
            path = scoped_path(root, str(manifest_path.parent.relative_to(root) / value) if structured else value)
            if not path.is_file() and key in required_sources:
                fail(result, "MISSING_PROFILE_SOURCE", f"Declared source does not exist: {key}={value}")
            result["sources"][key] = str(path.relative_to(root))
        for value in SYSTEM_SOURCES:
            if not scoped_path(root, value).is_file():
                fail(result, "MISSING_PROFILE_SOURCE", f"Required system file does not exist: {value}")
        result["system_sources"] = list(SYSTEM_SOURCES)
        strategy = result["sources"].get("strategy")
        if strategy and (root / strategy).is_file():
            result["strategy_source_sha256"] = sha256(root / strategy)
    except (OSError, ValueError, yaml.YAMLError, SchemaError) as error:
        fail(result, "INVALID_PROFILE", str(error))
    if result.get("manifest"):
        apply_readiness(result, check_readiness(result, root, mode, platform, pillar))
    finish(result)
    result["continue"] = result["valid"]
    return finish(result)


def check_strategy(report, context, repository_root=ROOT):
    """Enforce recorded judgments; do not invent an originality/NLP evaluator."""
    result = {"errors": [], "continue": False}
    previous = context.get("readiness", {})
    apply_readiness(result, check_readiness(context, repository_root, previous.get("mode", "draft"), previous.get("platform", "instagram")))
    if result["errors"]:
        result["errors"].extend(error for error in context["errors"] if error not in result["errors"])
        return finish(result)
    if not context["valid"]:
        result["errors"].extend(context["errors"])
        return finish(result)
    try:
        if isinstance(report, (str, Path)):
            report = validator.read_document(report)
        if not isinstance(report, dict):
            raise ValueError("Strategy checkpoint must be an object")
        for field in ("profile", "idea"):
            if report.get(field) != context[field]:
                fail(result, "STRATEGY_GATE_FAILED", f"Strategy checkpoint {field} does not match the selected run")
        source = result["readiness"]["sources"]["strategy"]
        if report.get("source") != source or report.get("source_sha256") != sha256(Path(repository_root) / source):
            fail(result, "STRATEGY_GATE_FAILED", "Strategy source/checksum is missing, stale, or from another profile")
        gates = report.get("gates", {})
        for name in GATES:
            gate = gates.get(name) if isinstance(gates, dict) else None
            if not isinstance(gate, dict) or gate.get("pass") is not True or not isinstance(gate.get("reason"), str) or not gate["reason"].strip():
                fail(result, "STRATEGY_GATE_FAILED", f"{name} must explicitly pass with a reason; stop before generation")
        result["checkpoint"] = report
    except (OSError, ValueError, yaml.YAMLError) as error:
        fail(result, "STRATEGY_GATE_FAILED", str(error))
    finish(result)
    result["continue"] = result["valid"]
    return result


def embedded(text, start, end):
    if start not in text or end not in text.split(start, 1)[1]:
        raise ValueError("Missing structured workflow section")
    return text.split(start, 1)[1].split(end, 1)[0]


def reject_markdown(text, status, errors):
    """Revoke linked output even when its structured source cannot be parsed."""
    text = re.sub(r"(?m)^\| status \|[^\n]*$", f"| status | {status} |", text, count=1)
    # Notes are untrusted text, including any old or conflicting verdict lines.
    text = re.sub(r"(Validation:[ \t]*)PASS\b", r"\1FAIL", text)
    text = re.sub(r"(?m)^Readiness: .*$", "Readiness: FAIL (workflow terminated)", text)
    text = re.sub(r"(?m)^CTA authorization: .*$", "CTA authorization: FAIL authorized=false (workflow terminated)", text)
    reasons = "\n".join(f"- {error['code']}: {error['message']}" for error in errors)
    return text.rstrip() + "\n\n## Validation failures\n\n" + reasons + "\n"


def markdown(content, checkpoint, notes, validation, coverage, source_name, readiness=None):
    """Serialize the validated copy as Markdown; no visual slide rendering."""
    cell = lambda value: str(value).replace("|", "\\|").replace("\n", " ")
    lines = [f"# {content.get('hook', '')}", "", "| Field | Value |", "| - | - |"]
    for label, field in [("status", "status"), ("content_id", "content_id"), ("profile", "profile"), ("type", "content_type"), ("pillar", "pillar"), ("angle", "angle"), ("keyword", "keyword"), ("offer", "offer_id")]:
        if field in {"keyword", "offer_id"} and field not in content:
            continue
        lines.append(f"| {label} | {cell(content.get(field, ''))} |")
    lines.extend(["", f"<!-- structured-content: {source_name} -->", f"Validation: {validation['result']}", f"Validation coverage: {coverage}", ""])
    if readiness is not None:
        lines.append("Readiness: " + " ".join(f"{field}={'PASS' if readiness[field + '_ready'] else 'FAIL'}" for field in ("draft", "public", "cta")))
    authorization = validation.get("cta_authorization")
    if isinstance(authorization, dict):
        lines.append(f"CTA authorization: {authorization['result']} authorized={str(authorization['authorized']).lower()} coverage={authorization['coverage']}")
    for error in validation.get("errors", []):
        lines.append(f"- {error['code']}: {error['message']}")
    lines.extend(["", "## Net new value filter", "", STRATEGY_START + json.dumps(checkpoint, ensure_ascii=False, indent=2, default=str) + STRATEGY_END, "", NOTES_START + notes + NOTES_END, "", "## Slides", ""])
    slides = content.get("slides", [])
    for slide in slides if isinstance(slides, list) else []:
        if not isinstance(slide, dict):
            continue
        lines.extend([f"### {slide.get('number', '')}. {slide.get('role', '')}: {slide.get('headline', '')}", "", str(slide.get("body", "")), "", f"Visual: {slide.get('visual_note', '')}", ""])
    lines.extend(["## CTA", "", str(content.get("cta", "")), "", "## Caption", "", str(content.get("caption", "")), ""])
    return "\n".join(lines)


def blocked_artifact_result(path, root, error=None, base=None, persist=False):
    """Revoke any visible ready state after an interrupted/terminal run."""
    result = copy.deepcopy(base) if isinstance(base, dict) else {
        "errors": [{"code": error[0], "message": error[1]}],
        "continue": False,
        "validation": None,
        "registry_coverage": None,
        "artifact_id": path.stem,
        "artifact_path": relative_path(root, path),
        "status": "draft",
    }
    if error is not None and base is not None:
        result["errors"] = [{"code": error[0], "message": error[1]}]
    result["artifact_id"] = path.stem
    result["artifact_path"] = relative_path(root, path)
    result["status"] = "draft"
    content = None
    try:
        content = validator.read_document(path)
        if isinstance(content, dict):
            result["content_id"] = content.get("content_id")
            result["profile"] = content.get("profile", content.get("profile_id"))
            content["status"] = "draft"
            path.write_text(yaml.safe_dump(content, sort_keys=False, allow_unicode=True))
    except Exception as exception:
        result["errors"].append({"code": "INVALID_CAROUSEL_ARTIFACT", "message": str(exception)})
    markdown_path = path.with_suffix(".md")
    if markdown_path.exists():
        try:
            text = markdown_path.read_text()
            if f"<!-- structured-content: {path.name} -->" in text:
                markdown_path.write_text(reject_markdown(text, "draft", result["errors"]))
        except Exception as exception:
            result["errors"].append({"code": "INVALID_CAROUSEL_ARTIFACT", "message": str(exception)})
    result = finish(result)
    if persist:
        path.with_suffix(".validation-failure.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def finalize_carousel(content_path, strategy_path=None, notes_path=None, target_status=None, repository_root=ROOT):
    """Serialize one artifact, persist interrupted state, then run finalization."""
    root = Path(repository_root).resolve()
    raw_path = Path(content_path)
    try:
        path = artifact_state.canonical_path(root, raw_path)
        state = artifact_state.state_path(path)
        with artifact_state.locked(path) as state:
            if state.exists():
                try:
                    previous = artifact_state.check_record(validator.read_document(state), path, root)
                except Exception as error:
                    return blocked_artifact_result(path, root, ("INVALID_WORKFLOW_STATE", str(error)))
                if previous["state"] == "FAIL":
                    failure_path = path.with_suffix(".validation-failure.json")
                    if failure_path.exists():
                        try:
                            failure = validator.read_document(failure_path)
                            if failure != previous["result"]:
                                return blocked_artifact_result(path, root, ("INVALID_WORKFLOW_STATE", "Terminal journal and failure record disagree; this artifact remains blocked"))
                        except Exception as error:
                            return blocked_artifact_result(path, root, ("INVALID_WORKFLOW_STATE", str(error)))
                    return blocked_artifact_result(path, root, base=previous["result"], persist=False)
                if previous["state"] == "RUNNING":
                    result = blocked_artifact_result(path, root, ("INVALID_WORKFLOW_STATE", "A previous finalizer process was interrupted; this artifact is terminal and must not be retried"), persist=True)
                else:
                    result = None
            else:
                result = None
            if result is not None:
                result["artifact_id"] = path.stem
                result["artifact_path"] = str(path.relative_to(root))
                result["errors"] = [{"code": "INVALID_WORKFLOW_STATE", "message": "A previous finalizer process was interrupted; this artifact is terminal and must not be retried"}]
                result = finish(result)
                artifact_state.atomic_json(state, {**artifact_state.binding(path, root), "state": "FAIL", "result": copy.deepcopy(result)})
                return result
            artifact_state.atomic_json(state, {**artifact_state.binding(path, root), "state": "RUNNING", "result": None})
            return _finalize_carousel(content_path=path, strategy_path=strategy_path, notes_path=notes_path,
                                      target_status=target_status, repository_root=root, journal_path=state)
    except Exception as error:
        result = {"errors": [{"code": "INVALID_WORKFLOW_STATE", "message": str(error)}], "continue": False}
        return finish(result)


def _finalize_carousel(content_path, strategy_path=None, notes_path=None, target_status=None, repository_root=ROOT, journal_path=None):
    """Validate a staged status before writing the paired Markdown/status result."""
    root = Path(repository_root).resolve()
    path = Path(content_path).resolve()
    result = {"errors": [], "continue": False, "validation": None, "registry_coverage": None}
    content = None
    markdown_path = path.with_suffix(".md")
    failure_path = path.with_suffix(".validation-failure.json")
    old_markdown = ""
    checkpoint = {}
    notes = ""
    owned = False
    record_failure = False
    export_started = False
    input_paths = []
    input_fingerprints = None
    try:
        path.relative_to(root / "content/carousels")
        match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})-[a-z0-9]+(?:-[a-z0-9]+)*", path.stem)
        if path.suffix != ".yaml" or not match:
            raise ValueError("Use content/carousels/YYYY-MM-DD-<slug>.yaml")
        date.fromisoformat(match.group(1))
        markdown_path.resolve().relative_to(root / "content/carousels")
        failure_path.resolve().relative_to(root / "content/carousels")
        result.update({
            "artifact_id": path.stem,
            "artifact_path": relative_path(root, path),
        })
        if failure_path.exists():
            # A new CLI process or an edited YAML file is not a new workflow run.
            previous = validator.read_document(failure_path)
            valid_terminal_record = (
                isinstance(previous, dict) and previous.get("valid") is False
                and previous.get("result") == "FAIL" and previous.get("continue") is False
                and isinstance(previous.get("errors"), list) and previous["errors"]
                and (previous.get("validation") is None or (
                    isinstance(previous["validation"], dict)
                    and previous["validation"].get("valid") is False
                    and previous["validation"].get("result") == "FAIL"
                ))
                and previous.get("artifact_id") == result["artifact_id"]
                and previous.get("artifact_path") == result["artifact_path"]
            )
            if not valid_terminal_record:
                fail(result, "INVALID_WORKFLOW_STATE", "Terminal failure record is malformed or bound to another artifact; this run remains blocked")
                return finish(result)
            return previous
        record_failure = True
        if markdown_path.exists():
            old_markdown = markdown_path.read_text()
            if f"<!-- structured-content: {path.name} -->" not in old_markdown:
                raise ValueError("Refusing to overwrite an existing Markdown file without this structured-content link")
            owned = True
        content = validator.read_document(path)
        if not isinstance(content, dict) or content.get("content_id") != path.stem:
            raise ValueError("content_id must equal the dated artifact filename stem")
        result["content_id"] = content.get("content_id")
        if not isinstance(content.get("profile"), str) or not isinstance(content.get("idea"), str):
            raise ValueError("Explicit profile and original idea metadata are required")
        owned = True
        status = target_status or content.get("status")
        readiness_mode = "public" if status in validator.PUBLIC_STATUSES else ("review" if status == "review" else "draft")
        context = resolve_request(f"--profile {content['profile']} {content['idea']}", root, mode=readiness_mode, platform=content.get("platform"), pillar=content.get("pillar"))
        result["profile"] = content["profile"]
        if not context["valid"]:
            result["errors"].extend(context["errors"])
        apply_readiness(result, check_readiness(context, root, readiness_mode, content.get("platform"), content.get("pillar"), content))
        if result["errors"]:
            return finish(result)
        notes = Path(notes_path).read_text() if notes_path else (embedded(old_markdown, NOTES_START, NOTES_END) if old_markdown else "")
        if strategy_path:
            checkpoint = validator.read_document(strategy_path)
        elif old_markdown:
            checkpoint = json.loads(embedded(old_markdown, STRATEGY_START, STRATEGY_END), object_pairs_hook=unique_json)
        else:
            fail(result, "STRATEGY_GATE_FAILED", "A strategy checkpoint is required before generating the first draft")
        gate = check_strategy(checkpoint, context, root)
        if gate.get("phase") == "readiness":
            result["phase"] = "readiness"
            result["readiness"] = gate["readiness"]
        for error in gate["errors"]:
            if error not in result["errors"]:
                result["errors"].append(error)
        for field in REQUIRED_CONTENT:
            if field not in content:
                fail(result, "MISSING_REQUIRED_FIELD", f"Carousel output is missing {field}")
        if not isinstance(status, str) or status not in {"draft", "review", "approved", "public", "killed"}:
            fail(result, "INVALID_CONTENT_SCHEMA", "Carousel finalization supports draft, review, approved, public, or killed")
        if result["errors"]:
            return finish(result)
        candidate = copy.deepcopy(content)
        candidate["status"] = status
        mode = "public" if status in validator.PUBLIC_STATUSES else ("review" if status == "review" else "draft")
        with tempfile.TemporaryDirectory(prefix=".validation-", dir=path.parent) as temporary:
            temporary = Path(temporary)
            candidate_path = temporary / "content.yaml"
            candidate_path.write_text(yaml.safe_dump(candidate, sort_keys=False, allow_unicode=True))
            claims_path = root / "knowledge/claims.yaml"
            evidence_path = root / "knowledge/evidence.yaml"
            if context["mode"] == "legacy-reference":
                result["registry_coverage"] = "legacy sources; schema/reference checks only, no registered creator proof"
                claims_path = temporary / "claims.yaml"
                evidence_path = temporary / "evidence.yaml"
                claims_path.write_text(yaml.safe_dump({"schema_version": "1.0", "profile": content["profile"], "claims": []}))
                evidence_path.write_text(yaml.safe_dump({"schema_version": "1.0", "profile": content["profile"], "evidence": []}))
            else:
                result["registry_coverage"] = "authoritative claim/evidence registries"
            input_paths = validation_input_paths(
                root, context, claims_path, evidence_path, path,
            )
            input_fingerprints = fingerprint_validation_inputs(root, input_paths)
            result["validation_inputs"] = {
                "status": "SNAPSHOTTED",
                "before": input_fingerprints,
            }
            validation = validation_decision(validator.validate_content(candidate_path, mode=mode, claims_path=claims_path, evidence_path=evidence_path, repository_root=root, expected_profile=content["profile"], require_assertions=context["mode"] != "legacy-reference"))
            after_validation = fingerprint_validation_inputs(root, input_paths)
            result["validation_inputs"]["after_validation"] = after_validation
            if after_validation != input_fingerprints:
                result["validation_inputs"]["status"] = "CHANGED"
                result["phase"] = "validation_state"
                fail(result, "VALIDATION_INPUT_CHANGED", "Authoritative validation input changed during validation; export is blocked")
            if context["mode"] == "legacy-reference":
                if not isinstance(validation.get("limitations"), list):
                    validation["limitations"] = []
                validation["limitations"].append("Legacy compatibility uses empty scoped registries; creator facts still require review against declared legacy sources.")
        result["validation"] = validation
        result["errors"].extend(validation["errors"])
        if "cta_authorization" in validation:
            result["cta_authorization"] = validation["cta_authorization"]
            if not validation["cta_authorization"]["valid"]:
                result["phase"] = "cta_authorization"
        if authoritative_pass(validation):
            # Re-read authorization at the export boundary, independently of a
            # validator PASS phrase or generated permission metadata.
            prior_phase = result.get("phase")
            result["phase"] = "cta_authorization"
            authorization = validation_decision(validator.authorize_cta(candidate, mode=mode, repository_root=root, require_cta=True))
            if authoritative_pass(authorization) and authorization.get("continue") is not True:
                fail(authorization, "CTA_UNAUTHORIZED", "CTA authorization must explicitly permit continuation")
            if authoritative_pass(authorization) and context["mode"] == "structured" and (validator.cta_used(candidate) or mode in validator.PUBLIC_MODES) and authorization.get("authorized") is not True:
                fail(authorization, "CTA_UNAUTHORIZED", "Structured CTA export requires explicit authoritative mechanics authorization")
            validator.finish(authorization)
            if not authorization["valid"]:
                authorization["authorized"] = False
            result["cta_authorization"] = authorization
            validation["cta_authorization"] = authorization
            result["errors"].extend(authorization["errors"])
            if authorization["errors"]:
                result["phase"] = "cta_authorization"
            elif not result["errors"]:
                result.pop("phase", None)
            elif prior_phase:
                result["phase"] = prior_phase
        if authoritative_pass(validation) and not result["errors"]:
            before_export = fingerprint_validation_inputs(root, input_paths)
            result["validation_inputs"]["before_export"] = before_export
            if before_export != input_fingerprints:
                result["validation_inputs"]["status"] = "CHANGED"
                result["phase"] = "validation_state"
                fail(result, "VALIDATION_INPUT_CHANGED", "Authoritative validation input changed before export; export is blocked")
        if authoritative_pass(validation) and not result["errors"]:
            content = candidate
            path.write_text(yaml.safe_dump(content, sort_keys=False, allow_unicode=True))
            export_started = True
            markdown_path.write_text(markdown(content, checkpoint, notes, validation, result["registry_coverage"], path.name, result["readiness"]))
            result["continue"] = True
            result["status"] = status
            result["files"] = {"content": str(path), "markdown": str(markdown_path)}
        return finish(result)
    except Exception as error:
        # Unexpected validator/export exceptions must also terminate this run.
        fail(result, "INVALID_CAROUSEL_ARTIFACT", str(error))
        return finish(result)
    finally:
        if result["errors"]:
            finish(result)
            # Revoke an old ready state, never export a new rejected carousel.
            if owned:
                blocked_status = "killed" if target_status == "killed" else "draft"
                result["status"] = blocked_status
                if isinstance(content, dict):
                    try:
                        content["status"] = blocked_status
                        path.write_text(yaml.safe_dump(content, sort_keys=False, allow_unicode=True))
                    except Exception as error:
                        fail(result, "INVALID_CAROUSEL_ARTIFACT", f"Could not write blocked source state: {error}")
                # A source write failure must not skip revoking its paired output.
                try:
                    if old_markdown:
                        markdown_path.write_text(reject_markdown(old_markdown, blocked_status, result["errors"]))
                    elif export_started:
                        markdown_path.unlink(missing_ok=True)
                except OSError as error:
                    fail(result, "INVALID_CAROUSEL_ARTIFACT", f"Could not revoke rejected Markdown output: {error}")
            if result["validation"] is not None:
                result["validation"].update({"valid": False, "result": "FAIL", "continue": False, "errors": copy.deepcopy(result["errors"])})
            finish(result)
            if record_failure:
                try:
                    result["artifact_id"] = result.get("artifact_id", path.stem)
                    result["artifact_path"] = result.get("artifact_path", relative_path(root, path))
                    failure_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
                except (OSError, TypeError, ValueError) as error:
                    fail(result, "INVALID_WORKFLOW_STATE", f"Could not preserve terminal failure record: {error}")
                    if result["validation"] is not None:
                        result["validation"].update({"valid": False, "result": "FAIL", "continue": False, "errors": copy.deepcopy(result["errors"])})
                    finish(result)
        if journal_path:
            try:
                result["artifact_id"] = result.get("artifact_id", path.stem)
                result["artifact_path"] = result.get("artifact_path", relative_path(root, path))
                if result["errors"]:
                    artifact_state.atomic_json(journal_path, {
                        **artifact_state.binding(path, root),
                        "state": "FAIL",
                        "result": copy.deepcopy(result),
                    })
                else:
                    artifact_state.atomic_json(journal_path, {
                        **artifact_state.binding(path, root),
                        "state": "COMPLETE",
                        "result": copy.deepcopy(result),
                        "outputs": artifact_state.output_hashes(path),
                    })
            except Exception as error:
                # A journal write failure leaves RUNNING state in place, so a
                # later process fails closed instead of treating the export as
                # complete. The current response is also made non-authoritative.
                if not result["errors"]:
                    fail(result, "INVALID_WORKFLOW_STATE", f"Could not preserve artifact transaction state: {error}")
                    result["status"] = "draft"
                    try:
                        if isinstance(content, dict):
                            content["status"] = "draft"
                            path.write_text(yaml.safe_dump(content, sort_keys=False, allow_unicode=True))
                        if markdown_path.exists():
                            markdown_path.write_text(reject_markdown(markdown_path.read_text(), "draft", result["errors"]))
                        failure_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
                    except Exception as revoke_error:
                        fail(result, "INVALID_CAROUSEL_ARTIFACT", f"Could not revoke an unjournaled export: {revoke_error}")
                    finish(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Resolve one /carousel request and report context blockers")
    prepare.add_argument("arguments", help="Raw /carousel arguments; quote as one string")
    prepare.add_argument("--mode", choices=validator.MODES, default="draft")
    prepare.add_argument("--platform", default="instagram")
    prepare.add_argument("--pillar", help="Explicit active pillar ID or exact configured name")
    gate = commands.add_parser("gate", help="Check strategy judgments before generation")
    gate.add_argument("checkpoint", type=Path)
    gate.add_argument("--mode", choices=validator.MODES, default="draft")
    gate.add_argument("--platform", default="instagram")
    finalize = commands.add_parser("finalize", help="Validate and write the paired content/Markdown artifacts")
    finalize.add_argument("content", type=Path)
    finalize.add_argument("--strategy", type=Path)
    finalize.add_argument("--notes", type=Path)
    finalize.add_argument("--status", choices=("draft", "review", "approved", "public", "killed"))
    args = parser.parse_args()
    if args.command == "prepare":
        result = resolve_request(args.arguments, mode=args.mode, platform=args.platform, pillar=args.pillar)
    elif args.command == "gate":
        try:
            report = validator.read_document(args.checkpoint)
            if not isinstance(report, dict) or not isinstance(report.get("profile"), str) or not isinstance(report.get("idea"), str):
                raise ValueError("Strategy checkpoint needs explicit profile and idea")
            context = resolve_request(f"--profile {report['profile']} {report['idea']}", mode=args.mode, platform=args.platform)
            result = check_strategy(report, context)
        except (OSError, ValueError, yaml.YAMLError) as error:
            result = finish({"errors": [{"code": "STRATEGY_GATE_FAILED", "message": str(error)}]})
    else:
        result = finalize_carousel(args.content, args.strategy, args.notes, args.status)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if authoritative_pass(result) and (args.command != "finalize" or result.get("continue") is True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
