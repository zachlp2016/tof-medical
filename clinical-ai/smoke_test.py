"""Synthetic-only real-model checks, intended for Docker --network none."""
import json
import os
from pathlib import Path
import tempfile
import unittest

TOKEN = "synthetic-test-service-token-1234567890"
secret = tempfile.NamedTemporaryFile(mode="w", delete=False)
secret.write(TOKEN)
secret.close()
os.environ["AI_SERVICE_TOKEN_FILE"] = secret.name

from fastapi.testclient import TestClient
from service import app
from engine import merge_word_fragments


class RealModelSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()
        cls.headers = {"Authorization": "Bearer " + TOKEN}

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        Path(secret.name).unlink(missing_ok=True)

    def post(self, text, operation="entities", headers=None):
        return self.client.post("/review", json={"text": text, "operation": operation},
                                headers=headers if headers is not None else self.headers)

    def test_01_real_models_ready(self):
        result = self.client.get("/readyz")
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json()["artifactsVerified"])
        self.assertEqual(result.json()["sdkVersion"], "3.0.0")
        self.assertEqual(len(result.json()["models"]["entities"]["revision"]), 40)

    def test_02_real_disease_extraction(self):
        text = "The patient has chronic myeloid leukemia and hypertension."
        response = self.post(text)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result["entities"])
        self.assertTrue(any("leukemia" in item["text"] for item in result["entities"]))
        for item in result["entities"]:
            self.assertEqual(text[item["start"]:item["end"]], item["text"])
            self.assertNotIn("assertion", item)
        self.assertNotIn("redactedText", result)

    def test_03_real_redaction_safe_projection(self):
        text = "Patient John Smith, born January 5, 1970, email john.smith@example.com, phone 415-555-1234, has hypertension."
        response = self.post(text, "deidentify")
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["entities"], [])
        self.assertGreater(result["redactionCount"], 0)
        self.assertNotIn("John Smith", result["redactedText"])
        self.assertNotIn("john.smith@example.com", result["redactedText"])
        self.assertNotIn("original_text", json.dumps(result))
        self.assertNotIn("pii_entities", json.dumps(result))

    def test_04_full_document_coverage(self):
        # The final disease and identifier are far beyond the first 512 tokens.
        prefix = "Routine encounter with no additional concerns. " * 170
        disease = self.post(prefix + "The patient has chronic myeloid leukemia.")
        self.assertEqual(disease.status_code, 200)
        self.assertTrue(any(item["start"] >= len(prefix) and "leukemia" in item["text"]
                            for item in disease.json()["entities"]))
        pii = self.post(prefix + "Patient Jane Anderson; email jane.anderson@example.com.", "deidentify")
        self.assertEqual(pii.status_code, 200)
        self.assertNotIn("jane.anderson@example.com", pii.json()["redactedText"])

    def test_05_unauthorized_no_input_echo(self):
        response = self.post("synthetic-sensitive-sentinel", headers={})
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("sentinel", response.text)

    def test_06_validation_no_input_echo(self):
        response = self.post("synthetic-sensitive-sentinel" * 1000)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {"error": "invalid_input"})
        invalid = self.client.post("/review", json={"text": "synthetic-sensitive-sentinel", "operation": "invalid"}, headers=self.headers)
        self.assertEqual(invalid.status_code, 422)
        self.assertNotIn("sentinel", invalid.text)

    def test_07_body_limit(self):
        response = self.client.post("/review", content=b"x" * 140000,
                                    headers={**self.headers, "Content-Type": "application/json"})
        self.assertEqual(response.status_code, 413)

    def test_08_single_concurrency(self):
        with app.state.engine.gate:
            response = self.post("The patient has hypertension.")
        self.assertEqual(response.status_code, 429)

    def test_09_origin_host_and_empty_input(self):
        self.assertEqual(self.post("test", headers={**self.headers, "Origin": "https://example.com"}).status_code, 403)
        self.assertEqual(self.post("test", headers={**self.headers, "Host": "untrusted.example"}).status_code, 400)
        self.assertEqual(self.post(" ").status_code, 422)

    def test_10_real_hypertension_word_fragments(self):
        text = ("Synthetic OpenMed QA only. Eleanor Pena has hypertension and "
                "type 2 diabetes. Contact eleanor@example.test.")
        response = self.post(text)
        self.assertEqual(response.status_code, 200)
        entities = response.json()["entities"]
        whole = [item for item in entities if item["text"] == "hypertension"]
        self.assertEqual(len(whole), 1)
        self.assertEqual(whole[0]["start"], text.index("hypertension"))
        self.assertEqual(whole[0]["end"], text.index("hypertension") + len("hypertension"))
        self.assertFalse(any(item["text"] in ("hyper", "tension") for item in entities))

    def test_11_merge_preserves_word_and_label_boundaries(self):
        def span(text, left, right, label="DISEASE", confidence=0.9):
            return {"text": text[left:right], "start": left, "end": right,
                    "label": label, "confidence": confidence}

        text = "hypertension"
        fragments = [span(text, 0, 5, confidence=0.939), span(text, 5, 12, confidence=0.919)]
        merged = merge_word_fragments(text, fragments)
        self.assertEqual(merged, [span(text, 0, 12, confidence=0.919)])
        self.assertEqual(fragments[0]["end"], 5)  # The source predictions stay intact.
        for text, left_end, right_start in (("hyper tension", 5, 6),
                                           ("hyper-tension", 6, 6),
                                           ("hyper.tension", 5, 5)):
            original = [span(text, 0, left_end), span(text, right_start, len(text))]
            self.assertEqual(merge_word_fragments(text, original), original)
        mixed = [span("hypertension", 0, 5), span("hypertension", 5, 12, label="OTHER")]
        self.assertEqual(merge_word_fragments("hypertension", mixed), mixed)

    def test_12_real_email_domain_redaction(self):
        text = ("Synthetic OpenMed QA only. Eleanor Pena has hypertension and "
                "type 2 diabetes. Contact eleanor@example.test.")
        response = self.post(text, "deidentify")
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertIn("Contact [REDACTED].", result["redactedText"])
        self.assertNotIn("eleanor@", result["redactedText"])
        self.assertNotIn("example.test", result["redactedText"])
        self.assertIn("Synthetic OpenMed QA only.", result["redactedText"])
        self.assertEqual(result["entities"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
