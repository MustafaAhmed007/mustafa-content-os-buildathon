"""Backward-compatible claim/content applicability schema contracts."""

import copy
from pathlib import Path
import unittest

from scripts.validate_claim_registry import RegistryValidator
from scripts.validate_content import read_document


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FIXTURE_ROOT = ROOT / "tests/fixtures/public"


class ApplicabilitySchemaTests(unittest.TestCase):
    def errors(self, schema, document):
        return list(RegistryValidator(read_document(ROOT / "schemas" / schema)).iter_errors(document))

    def test_existing_registries_and_content_remain_schema_compatible(self):
        for schema, path in [("claim-registry.schema.json", "knowledge/claims.yaml"), ("evidence-registry.schema.json", "knowledge/evidence.yaml"), ("content-item.schema.json", "content/valid.yaml")]:
            with self.subTest(schema=schema):
                self.assertEqual(self.errors(schema, read_document(PUBLIC_FIXTURE_ROOT / path)), [])

    def test_claim_applicability_is_optional_but_strictly_typed(self):
        registry = read_document(PUBLIC_FIXTURE_ROOT / "knowledge/claims.yaml")
        registry["claims"][0]["applicability"] = {"assertion_types": ["identity"]}
        self.assertEqual(self.errors("claim-registry.schema.json", registry), [])
        for value in [{}, {"assertion_types": ["invented"]}, {"assertion_types": ["identity", "identity"]}, {"assertion_types": ["identity"], "verification_status": "verified"}]:
            with self.subTest(value=value):
                registry["claims"][0]["applicability"] = value
                self.assertTrue(self.errors("claim-registry.schema.json", registry))

    def test_assertion_contract_rejects_missing_fields_unknown_fields_and_wrong_types(self):
        content = read_document(PUBLIC_FIXTURE_ROOT / "content/valid.yaml")
        assertion = {"assertion_id": "fixture-name", "target": "/caption", "text": "Example Creator", "assertion_type": "identity", "subject": "Example Creator", "claim_refs": ["fixture-public-name"]}
        content["assertions"] = [assertion]
        self.assertEqual(self.errors("content-item.schema.json", content), [])
        for field in ["assertion_id", "target", "text", "assertion_type", "claim_refs"]:
            with self.subTest(field=field):
                invalid = copy.deepcopy(content)
                del invalid["assertions"][0][field]
                self.assertTrue(self.errors("content-item.schema.json", invalid))
        for field, value in [("verification_status", "verified"), ("assertion_type", "invented"), ("claim_refs", "mustafa-public-name"), ("span", {"start": -1, "end": 2})]:
            with self.subTest(field=field):
                invalid = copy.deepcopy(content)
                invalid["assertions"][0][field] = value
                self.assertTrue(self.errors("content-item.schema.json", invalid))

    def test_quantitative_metadata_requires_scoped_numeric_measurement(self):
        registry = read_document(PUBLIC_FIXTURE_ROOT / "knowledge/claims.yaml")
        quantity = {"metric": "time_saved", "value": 5, "unit": "hours", "period": "fixture-week"}
        registry["claims"][0]["applicability"] = {"assertion_types": ["quantitative_result"], "quantitative": quantity}
        self.assertEqual(self.errors("claim-registry.schema.json", registry), [])
        for field in quantity:
            with self.subTest(field=field):
                invalid = copy.deepcopy(registry)
                del invalid["claims"][0]["applicability"]["quantitative"][field]
                self.assertTrue(self.errors("claim-registry.schema.json", invalid))
        invalid = copy.deepcopy(registry)
        invalid["claims"][0]["applicability"]["quantitative"]["value"] = True
        self.assertTrue(self.errors("claim-registry.schema.json", invalid))


if __name__ == "__main__":
    unittest.main()
