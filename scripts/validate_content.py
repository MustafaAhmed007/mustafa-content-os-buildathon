"""Read-only deterministic validation of explicit content metadata and references."""

import argparse
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit

import yaml
from jsonschema.exceptions import SchemaError

if __package__:
    from .validate_claim_registry import FORMATS, RegistryValidator, UniqueSafeLoader
    from .validate_evidence_registry import (
        CLAIM_SCHEMA,
        DEFAULT_CLAIMS,
        DEFAULT_EVIDENCE,
        DEFAULT_SCHEMA as EVIDENCE_SCHEMA,
        ROOT,
        read_document,
        resolve_pointer,
        validate_evidence_registry,
    )
else:
    from validate_claim_registry import FORMATS, RegistryValidator, UniqueSafeLoader
    from validate_evidence_registry import (
        CLAIM_SCHEMA,
        DEFAULT_CLAIMS,
        DEFAULT_EVIDENCE,
        DEFAULT_SCHEMA as EVIDENCE_SCHEMA,
        ROOT,
        read_document,
        resolve_pointer,
        validate_evidence_registry,
    )


DEFAULT_SCHEMA = ROOT / "schemas/content-item.schema.json"
MODES = ("draft", "review", "approved", "public")
PUBLIC_MODES = {"approved", "public"}
PUBLIC_STATUSES = {"approved", "public", "scheduled", "published"}
REFERENCE_ID = re.compile(r"[a-z][a-z0-9-]*")
ASSERTION_CLAIM_TYPES = {
    "identity": {"identity_claim"}, "positioning": {"positioning_claim"},
    "repository_existence": {"project_claim"}, "project_existence": {"project_claim"},
    "quantitative_result": {"metric_claim", "result_claim"},
    "operational_performance": {"metric_claim", "result_claim"},
    "externally_attributed": {"testimonial_claim"},
}
RESULT_VERIFICATION = {"verified", "first_party_verified", "third_party_verified"}
CTA_COMPONENTS = {"cta_type": "primary_mechanic", "keyword": "keyword", "offer_id": "offer_selection",
                  "destination": "destination_url", "delivery_asset": "delivery_asset", "conversion_path": "conversion_path"}
CAROUSEL_TYPES = {"carousel", "listicle", "myth vs fact", "step by step", "before and after", "tool stack", "story", "comparison", "checklist"}
LIMITATIONS = [
    "Assertions are explicit and copy-bound; prose and numerical claims are not extracted or truth-classified.",
    "Non-factual declarations are author classifications, not authoritative natural-language truth detection.",
    "Artifact integrity and exact scope matching are not source authenticity or independent factual verification.",
    "Expiry policy and prose publication rules are reported, not automatically evaluated.",
    "PASS is not human approval, profile activation, or permission to run publishing.",
]


def pointer(parts):
    return "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def add_error(result, code, path, message):
    error = {"code": code, "path": path, "message": message}
    if error not in result["errors"]:
        result["errors"].append(error)


def finish(result):
    result["valid"] = not result["errors"]
    result["result"] = "PASS" if result["valid"] else "FAIL"
    result["continue"] = result["valid"]
    return result


def schema_errors(result, document, schema_path, scope, invalid_code):
    schema = read_document(schema_path)
    RegistryValidator.check_schema(schema)
    validator = RegistryValidator(schema, format_checker=FORMATS)
    errors = sorted(
        validator.iter_errors(document),
        key=lambda error: (pointer(error.absolute_path), error.message),
    )
    for error in errors:
        parts = list(error.absolute_path)
        path = pointer([scope, *parts])
        references = "claim_refs" in parts or "evidence_refs" in parts or (
            scope == "content" and parts and parts[0] == "claims"
        )
        if error.validator == "required":
            for field in error.validator_value:
                if field not in error.instance:
                    add_error(result, "MISSING_REQUIRED_FIELD", path + "/" + field, f"Missing required field: {field}")
        elif scope == "content" and error.validator == "anyOf" and not parts:
            add_error(result, "MISSING_REQUIRED_FIELD", "/content/profile", "Either profile or legacy profile_id is required")
        elif error.validator in {"uniqueItems", "x-unique-by"}:
            code = "DUPLICATE_REFERENCE" if references else "DUPLICATE_ID"
            add_error(result, code, path, error.message)
        else:
            code = "MALFORMED_REFERENCE" if references else invalid_code
            add_error(result, code, path, error.message)


def collect_references(result, values, path):
    references = []
    seen = set()
    for index, value in enumerate(values):
        location = path + f"/{index}"
        if not REFERENCE_ID.fullmatch(value):
            add_error(result, "MALFORMED_REFERENCE", location, f"Malformed reference: {value!r}")
        elif value in seen:
            add_error(result, "DUPLICATE_REFERENCE", location, f"Duplicate reference: {value!r}")
        else:
            seen.add(value)
            references.append((value, location))
    return references


def copy_fields(content):
    """Only rendered copy is eligible as an assertion target, never registry IDs."""
    fields = {"/" + key: value for key in ("hook", "caption", "cta") if isinstance((value := content.get(key)), str) and value.strip()}
    for index, slide in enumerate(content.get("slides", [])):
        for key in ("headline", "body", "visual_note"):
            value = slide.get(key)
            if isinstance(value, str) and value.strip():
                fields[f"/slides/{index}/{key}"] = value
    return fields


def evidence_value(evidence, root):
    path = (Path(root) / evidence["locator"]["path"]).resolve()
    path.relative_to(Path(root).resolve())
    return resolve_pointer(read_document(path), evidence["locator"]["selector"])


def scoped_quantity(value):
    if not isinstance(value, dict) or not {"metric", "value", "unit", "period"}.issubset(value):
        return False
    if not isinstance(value["value"], (int, float)) or isinstance(value["value"], bool):
        return False
    if isinstance(value["value"], float) and not math.isfinite(value["value"]):
        return False
    return all(isinstance(value[field], str) and bool(value[field].strip()) and not re.search(
        r"\b(?:TODO[_ -]*VERIFY|unresolved|incomplete|placeholder|unknown|TBD)\b", value[field], re.IGNORECASE
    ) for field in ("metric", "unit", "period"))


def supported_types(claim, evidence_index):
    allowed = {kind for kind, types in ASSERTION_CLAIM_TYPES.items() if claim["claim_type"] in types}
    if "applicability" in claim:
        return allowed & set(claim["applicability"]["assertion_types"])
    if claim["claim_type"] == "identity_claim":
        return {"identity"}
    if claim["claim_type"] == "positioning_claim":
        return {"positioning"}
    if claim["claim_type"] == "project_claim" and claim["source_type"] == "profile_observation" and any(
        evidence_index.get(ref, {}).get("evidence_type") == "repository" for ref in claim["evidence_refs"]
    ):
        return {"repository_existence"}
    # A metric/result/project label alone supplies no measurement or result scope.
    return set()


def supported_statements(claim, evidence_index, root):
    statements = {claim["claim"], *claim.get("applicability", {}).get("statements", [])}
    if claim["claim_type"] == "identity_claim" and claim["source"].partition("#")[2] == "identity.name":
        statements.add(claim["subject"])
    if claim["claim_type"] in {"identity_claim", "positioning_claim"}:
        source, _, selector = claim["source"].partition("#")
        leaf = selector.rsplit(".", 1)[-1]
        for ref in claim["evidence_refs"]:
            evidence = evidence_index.get(ref)
            if not evidence or evidence["subject"] != claim["subject"] or evidence["evidence_type"] != "profile" or evidence["source"] != source:
                continue
            try:
                value = evidence_value(evidence, root)
                captured_field = evidence["locator"]["selector"].rsplit("/", 1)[-1]
                if isinstance(value, dict):
                    value = value.get(leaf) if captured_field == selector.split(".", 1)[0] else None
                elif captured_field != leaf:
                    value = None
                if isinstance(value, str) and value.strip() and value != "TODO_VERIFY":
                    statements.add(value)
            except (OSError, ValueError, KeyError, IndexError, yaml.YAMLError):
                pass  # Artifact errors are reported by the existing integrity pass.
    return statements


def validate_applicability(result, content, claim_index, evidence_index, root, require_assertions):
    fields = copy_fields(content)
    covered = {target: set() for target in fields}
    seen = set()
    for index, assertion in enumerate(content.get("assertions", [])):
        start_errors = len(result["errors"])
        location = f"/content/assertions/{index}"
        identifier, kind = assertion["assertion_id"], assertion["assertion_type"]
        report = {"assertion_id": identifier, "target": assertion["target"], "text": assertion["text"], "assertion_type": kind, "claims": []}

        def error(code, message, field=""):
            add_error(result, code, location + ("/" + field if field else ""), f"Assertion {identifier!r}: {message}")

        if identifier in seen:
            error("DUPLICATE_ID", "Assertion IDs must be unique", "assertion_id")
        seen.add(identifier)
        target = assertion["target"]
        if target not in fields:
            error("INVALID_ASSERTION_TARGET", f"Target {target!r} is not a nonempty rendered copy field", "target")
        else:
            span = assertion.get("span", {"start": 0, "end": len(fields[target])})
            start, end = span["start"], span["end"]
            if not 0 <= start < end <= len(fields[target]) or fields[target][start:end] != assertion["text"]:
                error("ASSERTION_TEXT_MISMATCH", f"Text/span does not match actual copy at {target}", "text")
            else:
                covered[target].update(range(start, end))
        public = result["public_facing"] or assertion.get("public_usage") == "public"
        if public and assertion.get("public_usage", "public") != "public":
            error("RESTRICTED_ASSERTION", "Private/internal/unresolved metadata cannot authorize a public assertion", "public_usage")
        if kind == "unknown":
            if public or assertion["claim_refs"] or "quantitative" in assertion:
                error("UNCLASSIFIED_ASSERTION", "Factual/public assertions require a supported explicit type", "assertion_type")
        elif kind == "non_factual":
            if assertion["claim_refs"] or assertion.get("evidence_refs") or "quantitative" in assertion:
                error("CLAIM_NOT_APPLICABLE", "Non-factual copy cannot borrow factual claim/evidence support or measurements")
        else:
            if not assertion["claim_refs"]:
                error("MISSING_ASSERTION_CLAIM", "An explicit supporting claim is required", "claim_refs")
            if not assertion.get("subject"):
                error("ASSERTION_SCOPE_MISMATCH", "An explicit matching subject is required", "subject")
            if kind == "quantitative_result" and "quantitative" not in assertion:
                error("ASSERTION_SCOPE_MISMATCH", "Quantitative results require metric, value, unit, and period", "quantitative")
            if "quantitative" in assertion and kind not in {"quantitative_result", "operational_performance"}:
                error("CLAIM_NOT_APPLICABLE", "Measurement metadata cannot be classified as identity/positioning/existence")
            for ref_index, ref in enumerate(assertion["claim_refs"]):
                ref_path = f"claim_refs/{ref_index}"
                if ref not in claim_index:
                    report["claims"].append({"claim_ref": ref, "reference_valid": False, "applicable": False})
                    error("UNKNOWN_CLAIM", f"Unknown attached claim {ref!r}", ref_path)
                    continue
                claim = claim_index[ref][1]
                types = supported_types(claim, evidence_index)
                claim_report = {"claim_ref": ref, "reference_valid": True, "applicable": False, "supported_assertion_types": sorted(types),
                                "verification_status": claim["verification_status"], "public_use": claim["public_use"]}
                report["claims"].append(claim_report)
                claim_errors = len(result["errors"])
                if kind not in types:
                    error("CLAIM_NOT_APPLICABLE", f"Claim {ref!r} ({claim['claim_type']}) cannot support {kind!r}", ref_path)
                    continue
                scope = claim.get("applicability", {})
                if assertion.get("subject") != claim["subject"]:
                    error("ASSERTION_SCOPE_MISMATCH", f"Claim {ref!r} has a different subject", ref_path)
                if assertion["text"] not in supported_statements(claim, evidence_index, root):
                    error("ASSERTION_TEXT_UNSUPPORTED", f"Claim {ref!r} does not authorize this exact statement; declare an approved statement in authoritative scope", ref_path)
                if kind == "positioning" and assertion.get("basis", "self_description") != "self_description":
                    error("ASSERTION_SCOPE_MISMATCH", f"Claim {ref!r} supports self-described positioning, not independently verified credentials/results", "basis")
                if claim["verification_status"] == "self_reported" and assertion.get("basis") == "independently_verified":
                    error("ASSERTION_SCOPE_MISMATCH", f"Claim {ref!r} remains self_reported", "basis")
                if kind == "repository_existence" and claim["source_type"] == "profile_observation":
                    if assertion.get("temporal_scope") != "historical":
                        error("ASSERTION_SCOPE_MISMATCH", f"Claim {ref!r} supports only the recorded historical repository observation", "temporal_scope")
                elif scope.get("temporal_scope") and assertion.get("temporal_scope") != scope["temporal_scope"]:
                    error("ASSERTION_SCOPE_MISMATCH", f"Claim {ref!r} has a different temporal scope", "temporal_scope")
                if kind == "externally_attributed" and (not scope.get("attribution") or assertion.get("attribution") != scope["attribution"]):
                    error("ASSERTION_SCOPE_MISMATCH", f"Claim {ref!r} requires the exact authorized attribution", "attribution")
                quantity = assertion.get("quantitative")
                if quantity is not None and (quantity != scope.get("quantitative") or not scoped_quantity(quantity)):
                    error("ASSERTION_SCOPE_MISMATCH", f"Claim {ref!r} does not support the declared metric/value/unit/period", "quantitative")
                high_risk = kind in {"quantitative_result", "operational_performance", "externally_attributed"}
                if high_risk:
                    if claim["status"] != "verified" or claim["verification_status"] not in RESULT_VERIFICATION or not claim["evidence_refs"]:
                        error("INSUFFICIENT_ASSERTION_EVIDENCE", f"Claim {ref!r} requires explicit verified claim-owned evidence; its verification classification is not upgraded", ref_path)
                    for evidence_ref in claim["evidence_refs"]:
                        evidence = evidence_index.get(evidence_ref)
                        permitted_types = {"metric", "first_party", "third_party", "document"} if kind != "externally_attributed" else {"testimonial", "third_party"}
                        sufficient = bool(evidence and evidence["verification_status"] in RESULT_VERIFICATION and evidence["evidence_type"] in permitted_types and evidence["subject"] == claim["subject"])
                        if sufficient:
                            try:
                                payload = evidence_value(evidence, root)
                                sufficient = isinstance(payload, dict) and payload.get("subject") == claim["subject"] and payload.get("statement") == claim["claim"]
                                if quantity is not None:
                                    sufficient = sufficient and scoped_quantity(payload.get("quantitative")) and payload.get("quantitative") == quantity
                                if kind == "externally_attributed":
                                    sufficient = sufficient and payload.get("attribution") == assertion.get("attribution")
                            except (OSError, ValueError, KeyError, IndexError, yaml.YAMLError):
                                sufficient = False
                        if not sufficient:
                            error("INSUFFICIENT_ASSERTION_EVIDENCE", f"Claim {ref!r}, evidence {evidence_ref!r}: no matching verified structured support for this assertion", ref_path)
                for evidence_ref in assertion.get("evidence_refs", []):
                    if evidence_ref not in claim["evidence_refs"]:
                        error("INSUFFICIENT_ASSERTION_EVIDENCE", f"Evidence {evidence_ref!r} is not owned by attached claim {ref!r}; direct references cannot replace its support", "evidence_refs")
                claim_report["applicable"] = len(result["errors"]) == claim_errors
        report["result"] = "FAIL" if len(result["errors"]) > start_errors else "PASS"
        result["assertions"].append(report)

    # Backward-compatible exact literals are safely bounded, never type-guessed.
    for target, text in fields.items():
        slide_match = re.fullmatch(r"/slides/(\d+)/.+", target)
        refs = content["slides"][int(slide_match.group(1))].get("claim_refs", []) if slide_match else content.get("claims", [])
        if not covered[target] and refs:
            applicable = []
            for ref in refs:
                claim = claim_index.get(ref, (None, None))[1]
                if claim and supported_types(claim, evidence_index) & {"identity", "positioning"} and text in supported_statements(claim, evidence_index, root):
                    applicable.append(ref)
            if applicable and len(applicable) == len(refs):
                covered[target].update(range(len(text)))
                result["assertions"].append({"assertion_id": None, "target": target, "assertion_type": "exact_supported_literal",
                                             "claim_refs": applicable, "result": "PASS"})
        if require_assertions and result["public_facing"] and any(not character.isspace() and index not in covered[target] for index, character in enumerate(text)):
            add_error(result, "UNCLASSIFIED_ASSERTION", "/content" + target, f"Public copy at {target} has no complete safe assertion classification; attached references {refs!r} do not authorize arbitrary prose")


def resolved_cta_value(value):
    return isinstance(value, str) and bool(value.strip()) and value.strip().lower() not in {"none", "null", "n/a"} and not re.search(
        r"\b(?:TODO[_ -]*VERIFY|unresolved|unknown|incomplete|placeholder|inferred|model[-_ ]generated|unavailable|disabled|TBD|TBC)\b|<[^>]+>", value, re.IGNORECASE)


def cta_used(content):
    slides = content.get("slides", [])
    return bool(content.get("cta") or content.get("keyword") or content.get("offer_id")) or "cta_mechanics" in content or any(
        isinstance(slide, dict) and slide.get("role") == "cta" and (slide.get("headline") or slide.get("body"))
        for slide in (slides if isinstance(slides, list) else []))


def authorize_cta(content, mode=None, repository_root=ROOT, require_cta=False):
    """Authorize declared mechanics from profile configuration, never claims/prose."""
    root = Path(repository_root).resolve()
    report = {"profile": None, "phase": "cta_authorization", "authorized": False, "omitted": False,
              "required": False, "coverage": "structured profile mechanics authorization", "checks": [], "errors": []}

    def check(component, path, passed, reason):
        report["checks"].append({"component": component, "path": path, "status": "PASS" if passed else "FAIL", "reason": reason})
        if not passed:
            add_error(report, "CTA_UNAUTHORIZED", path, f"{component}: {reason}")

    def path_for(value, parent=root):
        if not resolved_cta_value(value):
            raise ValueError("Authoritative configuration path is unresolved")
        path = (parent / value).resolve()
        path.relative_to(root)
        return path

    def document(path):
        path = path.resolve()
        path.relative_to(root)
        if path.suffix == ".md":
            match = re.match(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", path.read_text(), re.DOTALL)
            if not match:
                raise ValueError("Required machine-readable YAML front matter is missing")
            data = yaml.load(match.group(1), Loader=UniqueSafeLoader)
        else:
            data = read_document(path)
        if not isinstance(data, dict):
            raise ValueError("Authoritative configuration must be an object")
        return data

    try:
        if not isinstance(content, dict):
            raise ValueError("CTA content must be an object")
        if mode is not None and (not isinstance(mode, str) or mode not in MODES):
            raise ValueError("CTA mode must be draft, review, approved, or public")
        profile = content.get("profile", content.get("profile_id"))
        report["profile"] = profile if isinstance(profile, str) else None
        if not resolved_cta_value(profile) or content.get("profile_id", profile) != profile:
            raise ValueError("Explicit content profile and any profile_id alias must agree")
        assertions = content.get("assertions", [])
        if not isinstance(assertions, list) or not isinstance(content.get("slides", []), list):
            raise ValueError("Assertions and slides must be arrays when supplied")
        if not isinstance(content.get("status", "draft"), str):
            raise ValueError("Content status must be an explicit string")
        public = mode in PUBLIC_MODES or content.get("status") in PUBLIC_STATUSES or any(
            isinstance(item, dict) and item.get("public_usage") == "public" for item in assertions)
        used = cta_used(content)
        required = public and (require_cta or str(content.get("content_type", "")).strip().lower() in CAROUSEL_TYPES)
        report.update(omitted=not used, required=required)
        if not used and not required and public:
            check("cta_mechanics", "/content/cta", True, "Non-carousel content with no CTA needs no mechanics authorization")
            return finish(report)
        if not used and not required and not (root / "profiles/active.yaml").is_file():
            check("private_omission", "/content/cta", True, "No CTA requested; no mechanics are authorized")
            return finish(report)
        active = document(root / "profiles/active.yaml")
        entries = [item for item in active.get("profiles", []) if isinstance(item, dict) and item.get("profile_id") == profile]
        if len(entries) != 1:
            raise ValueError("Selected profile must have exactly one authoritative manifest entry")
        manifest_path = path_for(entries[0].get("manifest"))
        manifest = document(manifest_path)
        check("profile", str(manifest_path.relative_to(root)), manifest.get("profile_id") == profile, "Manifest must match selected profile")
        allowed_statuses = {"active"} if public and (used or required) else {"active", "draft"}
        check("profile_status", str(manifest_path.relative_to(root)) + "#status", manifest.get("status") in allowed_statuses, "Explicit profile status must permit the requested use")
        if manifest.get("mode") == "legacy-reference":
            report["coverage"] = "legacy declared-source compatibility; rendered mechanics are not structurally authorized"
            if "cta_mechanics" in content:
                check("cta_mechanics", "/content/cta_mechanics", False, "Legacy free-form policy cannot authorize new structured mechanics; explicit source migration is required")
            return finish(report)
        check("profile_mode", str(manifest_path.relative_to(root)) + "#mode", manifest.get("mode") == "structured", "Structured CTA authorization requires a structured profile")
        files = manifest.get("files", {})
        if not isinstance(files, dict):
            raise ValueError("Structured profile files must be an object")
        if not used and not required:
            # Omitting a CTA grants no mechanics authorization. Private body permission
            # comes from the explicit manifest status, subject to any local denial.
            policy = {}
            if resolved_cta_value(files.get("offers")):
                offers_path = path_for(files["offers"], manifest_path.parent)
                if offers_path.is_file():
                    offers = document(offers_path)
                    check("offers_scope", str(offers_path.relative_to(root)) + "#profile_id", offers.get("profile_id") == profile, "Private omission policy must belong to selected profile")
                    policy = offers.get("cta_policy", {})
                    if not isinstance(policy, dict):
                        raise ValueError("Configured private omission policy must be an object")
            allowance = policy.get("allow_private_draft_without_cta", True)
            check("private_omission", "/content/cta", allowance is True, "Private body-only drafting must be permitted; omitted CTA is not authorized")
            return finish(report)
        mechanics = content.get("cta_mechanics")
        check("cta_mechanics", "/content/cta_mechanics", isinstance(mechanics, dict), "Public/used CTA requires explicit classified mechanics")
        mechanics = mechanics if isinstance(mechanics, dict) else {}
        check("contract", "/content/cta_mechanics", not (set(mechanics) - {*CTA_COMPONENTS, "account"}), "Generated permission/status fields cannot grant authorization")
        offers_path = path_for(files.get("offers"), manifest_path.parent)
        channels_path = path_for(files.get("channels"), manifest_path.parent)
        offers, channels = document(offers_path), document(channels_path)
        check("offers_scope", str(offers_path.relative_to(root)) + "#profile_id", offers.get("profile_id") == profile, "Offers must belong to selected profile")
        check("channels_scope", str(channels_path.relative_to(root)) + "#profile_id", channels.get("profile_id") == profile, "Channels must belong to selected profile")
        policy = offers.get("cta_policy")
        check("policy", str(offers_path.relative_to(root)) + "#cta_policy", isinstance(policy, dict), "Explicit CTA policy is required")
        policy = policy if isinstance(policy, dict) else {}
        check("policy_permission", str(offers_path.relative_to(root)) + "#cta_policy.public_use", policy.get("public_use", offers.get("public_use")) == "public", "CTA policy requires explicit local/inherited public permission")
        for flag in ("enabled", "publishable"):
            if flag in policy:
                check("policy_" + flag, str(offers_path.relative_to(root)) + "#cta_policy." + flag, policy[flag] is True, "A disabled or unresolved policy flag cannot authorize CTA use")
        if "status" in policy:
            check("policy_status", str(offers_path.relative_to(root)) + "#cta_policy.status", policy["status"] in ("active", "verified", "ready", "configured"), "CTA policy must not be inactive/unavailable")
        for component, field in CTA_COMPONENTS.items():
            actual, expected = mechanics.get(component), policy.get(field)
            passed = resolved_cta_value(actual) and resolved_cta_value(expected) and actual == expected
            if component == "destination" and passed:
                parsed = urlsplit(expected)
                passed = parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not any(character.isspace() for character in expected)
            check(component, "/content/cta_mechanics/" + component, passed, f"Must exactly match explicitly authorized cta_policy.{field}; no inferred fallback")
        for alias in ("keyword", "offer_id"):
            if alias in content:
                check(alias, "/content/" + alias, resolved_cta_value(content[alias]) and content[alias] == mechanics.get(alias), "Existing top-level metadata must agree with structured mechanics")
        selected = [item for item in offers.get("offers", []) if isinstance(item, dict) and item.get("id") == policy.get("offer_selection")]
        check("offer_selection", str(offers_path.relative_to(root)) + "#offers", len(selected) == 1, "Exactly one explicitly selected offer is required")
        offer = selected[0] if len(selected) == 1 else {}
        for component, passed in (("offer_status", offer.get("status") in ("active", "verified", "ready", "configured")),
                                  ("offer_publishable", offer.get("publishable") is True),
                                  ("offer_permission", offer.get("public_use", offers.get("public_use")) == "public")):
            check(component, str(offers_path.relative_to(root)) + "#offers[" + str(policy.get("offer_selection")) + "]", passed, "Selected offer must be available, publishable, and explicitly public")
        selected = [item for item in channels.get("channels", []) if isinstance(item, dict) and item.get("id") == content.get("platform")]
        check("channel", str(channels_path.relative_to(root)) + "#channels", len(selected) == 1, "Exactly one selected publishing channel is required; no fallback")
        channel = selected[0] if len(selected) == 1 else {}
        for component, record, source in (("offer_enabled", offer, offers_path), ("channel_enabled", channel, channels_path)):
            if "enabled" in record:
                check(component, str(source.relative_to(root)) + "#enabled", record["enabled"] is True, "Explicit enabled flags must be true booleans")
        for component, passed in (("channel_publishable", channel.get("publishable") is True), ("channel_permission", channel.get("public_use") == "public"),
                                  ("channel_status", channel.get("status") in ("active", "verified", "ready", "configured")),
                                  ("channel_verification", channel.get("verification_status") == "verified")):
            check(component, str(channels_path.relative_to(root)) + "#channels[" + str(content.get("platform")) + "]", passed, "Selected account must be explicitly available and authorized for public use")
        expected, actual = channel.get("handle_or_url"), mechanics.get("account")
        check("account", "/content/cta_mechanics/account", resolved_cta_value(actual) and resolved_cta_value(expected) and actual == expected, "Account must exactly match the explicitly configured selected channel")
        if require_cta or str(content.get("content_type", "")).strip().lower() in CAROUSEL_TYPES:
            types = channel.get("content_types")
            check("channel_content_types", str(channels_path.relative_to(root)) + "#content_types", isinstance(types, list) and bool(types)
                  and all(resolved_cta_value(item) for item in types) and any(item.lower() in {"carousel", "carousels"} for item in types), "Selected channel must explicitly support carousels")
        report["authorized"] = not report["errors"]
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as error:
        check("configuration", "/profile/cta_policy", False, str(error))
    return finish(report)


def validate_content(
    content,
    mode=None,
    claims_path=DEFAULT_CLAIMS,
    evidence_path=DEFAULT_EVIDENCE,
    schema_path=DEFAULT_SCHEMA,
    repository_root=ROOT,
    expected_profile="mustafa",
    require_assertions=True,
):
    """Validate a mapping or YAML/JSON path without changing any source files."""
    result = {
        "result": "FAIL", "valid": False, "content_id": None, "profile": None,
        "mode": None, "public_facing": False, "errors": [], "claims": [],
        "evidence": [], "assertions": [], "limitations": list(LIMITATIONS),
        "applicability_coverage": "structured assertions and exact supported literals" if require_assertions else "legacy reference compatibility; undeclared prose is not applicability-checked",
    }
    try:
        if isinstance(content, (str, Path)):
            content = read_document(content)
        if isinstance(content, dict):
            for field in ("content_id", "profile"):
                value = content.get(field, content.get("profile_id") if field == "profile" else None)
                result[field] = value if isinstance(value, str) else None
            status = content.get("status")
            inferred = status if isinstance(status, str) and status in MODES else "draft"
            if isinstance(status, str) and status in {"scheduled", "published"}:
                inferred = "public"
            result["mode"] = mode if isinstance(mode, str) else inferred
            result["public_facing"] = result["mode"] in PUBLIC_MODES or (
                isinstance(status, str) and status in PUBLIC_STATUSES
            )
            if isinstance(content.get("assertions"), list) and any(isinstance(item, dict) and item.get("public_usage") == "public" for item in content["assertions"]):
                result["public_facing"] = True
        if mode is not None and (not isinstance(mode, str) or mode not in MODES):
            add_error(result, "INVALID_VALIDATION_MODE", "/mode", f"Mode must be one of {MODES}")
        schema_errors(result, content, schema_path, "content", "INVALID_CONTENT_SCHEMA")
    except (OSError, ValueError, yaml.YAMLError, SchemaError) as error:
        add_error(result, "INVALID_CONTENT_SCHEMA", "/content", str(error))
    if result["errors"]:
        return finish(result)

    for field in ("schema_version", "content_id", "platform", "content_type", "status", "profile", "profile_id"):
        if field in content and not content[field].strip():
            add_error(result, "MISSING_REQUIRED_FIELD", f"/content/{field}", f"Metadata field must not be blank: {field}")

    registries = {}
    for name, path, schema in [
        ("claim", claims_path, CLAIM_SCHEMA),
        ("evidence", evidence_path, EVIDENCE_SCHEMA),
    ]:
        code = f"INVALID_{name.upper()}_REGISTRY"
        try:
            registries[name] = read_document(path)
            schema_errors(result, registries[name], schema, f"{name}_registry", code)
        except (OSError, ValueError, yaml.YAMLError, SchemaError) as error:
            add_error(result, code, f"/{name}_registry", str(error))
    if result["errors"]:
        return finish(result)

    claims = registries["claim"]
    evidence = registries["evidence"]
    if content.get("profile_id", result["profile"]) != result["profile"]:
        add_error(result, "PROFILE_MISMATCH", "/content/profile_id", "profile and profile_id must agree")
    for path, profile in [
        ("/content/profile", result["profile"]),
        ("/claim_registry/profile", claims["profile"]),
        ("/evidence_registry/profile", evidence["profile"]),
    ]:
        if profile != expected_profile:
            add_error(result, "PROFILE_MISMATCH", path, f"Expected {expected_profile} profile, found {profile!r}")

    claim_index = {record["claim_id"]: (index, record) for index, record in enumerate(claims["claims"])}
    evidence_index = {record["evidence_id"]: record for record in evidence["evidence"]}
    for index, claim in enumerate(claims["claims"]):
        refs = collect_references(result, claim["evidence_refs"], f"/claim_registry/claims/{index}/evidence_refs")
        for ref, path in refs:
            if ref not in evidence_index:
                add_error(result, "UNKNOWN_EVIDENCE", path, f"Claim {claim['claim_id']!r} references unknown evidence {ref!r}")

    claim_refs = collect_references(result, content.get("claims", []), "/content/claims")
    evidence_refs = collect_references(result, content.get("evidence_refs", []), "/content/evidence_refs")
    for index, assertion in enumerate(content.get("assertions", [])):
        claim_refs.extend(collect_references(result, assertion["claim_refs"], f"/content/assertions/{index}/claim_refs"))
        evidence_refs.extend(collect_references(result, assertion.get("evidence_refs", []), f"/content/assertions/{index}/evidence_refs"))
    slide_numbers = set()
    for index, slide in enumerate(content.get("slides", [])):
        if slide["number"] in slide_numbers:
            add_error(result, "DUPLICATE_ID", f"/content/slides/{index}/number", f"Duplicate slide number: {slide['number']}")
        slide_numbers.add(slide["number"])
        claim_refs.extend(collect_references(result, slide.get("claim_refs", []), f"/content/slides/{index}/claim_refs"))
        evidence_refs.extend(collect_references(result, slide.get("evidence_refs", []), f"/content/slides/{index}/evidence_refs"))

    resolved_claims = set()
    for ref, path in claim_refs:
        if ref not in claim_index:
            add_error(result, "UNKNOWN_CLAIM", path, f"Unknown claim: {ref!r}")
            continue
        if ref in resolved_claims:
            continue  # The same claim may annotate multiple distinct locations.
        resolved_claims.add(ref)
        index, claim = claim_index[ref]
        result["claims"].append({field: claim[field] for field in (
            "claim_id", "claim_type", "status", "verification_status", "public_use",
            "publication_rule", "expires_at", "evidence_refs",
        )})
        restrictions = []
        if claim["public_use"] != "public":
            restrictions.append(f"public_use={claim['public_use']}")
        if claim["status"] != "verified":
            restrictions.append(f"status={claim['status']}")
        if claim["verification_status"] in {"unverified", "expired"}:
            restrictions.append(f"verification_status={claim['verification_status']}")
        if result["public_facing"] and restrictions:
            add_error(result, "RESTRICTED_CLAIM", path, f"Claim {ref!r} cannot be used publicly: {', '.join(restrictions)}")
        evidence_refs.extend((e, f"/claim_registry/claims/{index}/evidence_refs/{i}") for i, e in enumerate(claim["evidence_refs"]))

    resolved_evidence = set()
    for ref, path in evidence_refs:
        if ref not in evidence_index:
            # The registry-link pass already reports missing claim-owned evidence.
            if path.startswith("/content/"):
                add_error(result, "UNKNOWN_EVIDENCE", path, f"Unknown evidence: {ref!r}")
            continue
        if ref in resolved_evidence:
            continue
        resolved_evidence.add(ref)
        record = evidence_index[ref]
        result["evidence"].append({field: record[field] for field in (
            "evidence_id", "evidence_type", "verification_status", "public_use", "expires_at",
        )})
        restrictions = []
        if record["public_use"] != "public":
            restrictions.append(f"public_use={record['public_use']}")
        if record["verification_status"] in {"unverified", "expired"}:
            restrictions.append(f"verification_status={record['verification_status']}")
        if result["public_facing"] and restrictions:
            add_error(result, "RESTRICTED_EVIDENCE", path, f"Evidence {ref!r} cannot be used publicly: {', '.join(restrictions)}")

    if not any(error["code"] in {"PROFILE_MISMATCH", "UNKNOWN_EVIDENCE", "MALFORMED_REFERENCE"} for error in result["errors"]):
        for error in validate_evidence_registry(evidence_path, claims_path, repository_root=repository_root):
            add_error(result, "INVALID_EVIDENCE_REGISTRY", "/evidence_registry", error)
    validate_applicability(result, content, claim_index, evidence_index, repository_root, require_assertions)
    if not result["errors"]:
        report = authorize_cta(content, mode=result["mode"], repository_root=repository_root)
        result["cta_authorization"] = report
        result["errors"].extend(report["errors"])
        if report["errors"]:
            result["phase"] = "cta_authorization"
    return finish(result)


def format_result(result):
    lines = [f"{result['result']} content_id={result['content_id']} profile={result['profile']} mode={result['mode']} public_facing={result['public_facing']}"]
    for error in result["errors"]:
        lines.append(f"- {error['code']} {error['path']}: {error['message']}")
    for claim in result["claims"]:
        lines.append(f"Claim {claim['claim_id']}: type={claim['claim_type']} status={claim['status']} verification_status={claim['verification_status']} public_use={claim['public_use']} expires_at={claim['expires_at']}")
        lines.append(f"  publication_rule: {claim['publication_rule']}")
    for evidence in result["evidence"]:
        lines.append(f"Evidence {evidence['evidence_id']}: verification_status={evidence['verification_status']} public_use={evidence['public_use']} expires_at={evidence['expires_at']}")
    authorization = result.get("cta_authorization")
    if isinstance(authorization, dict):
        lines.append(f"CTA authorization: {authorization['result']} authorized={str(authorization['authorized']).lower()} coverage={authorization['coverage']}")
    lines.extend(f"Limit: {limitation}" for limitation in result["limitations"])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("content", type=Path, help="Structured YAML/JSON content item")
    parser.add_argument("--mode", choices=MODES, help="Defaults to content status; public-facing statuses cannot be downgraded")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    parser.add_argument("--claims", type=Path, default=DEFAULT_CLAIMS)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--profile", default="mustafa", help="Expected scope of content and both registries; defaults to mustafa")
    args = parser.parse_args()
    result = validate_content(
        args.content, mode=args.mode, claims_path=args.claims, evidence_path=args.evidence,
        expected_profile=args.profile, repository_root=args.repository_root,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.format == "json" else format_result(result))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
