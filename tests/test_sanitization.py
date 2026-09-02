import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from engineering_flow.sanitization import sanitize, sanitize_payload, sanitize_text  # noqa: E402


class SanitizationTests(unittest.TestCase):
    def test_exact_secret_and_credential_shaped_values_are_redacted(self):
        text = "api_key=abc123 token: xyz password='open-sesame' Bearer bearer-token"
        result = sanitize_text(text, ("open-sesame",))
        self.assertNotIn("abc123", result)
        self.assertNotIn("xyz", result)
        self.assertNotIn("open-sesame", result)
        self.assertNotIn("bearer-token", result)
        self.assertIn("[REDACTED]", result)

    def test_nested_payload_redacts_sensitive_keys_without_mutating_input(self):
        payload = {"settings": {"api_key": "secret-value"}, "items": ["secret-value"]}
        result = sanitize(payload, ("secret-value",))
        self.assertEqual(result["settings"]["api_key"], "[REDACTED]")
        self.assertEqual(result["items"], ["[REDACTED]"])
        self.assertEqual(payload["settings"]["api_key"], "secret-value")

    def test_persisted_payload_removes_nested_environment_mappings(self):
        payload = {
            "keep": "value",
            "env": {"PATH": "C:/sensitive-path"},
            "nested": [{"Environment": {"HOME": "C:/sensitive-home"}}],
        }

        result = sanitize_payload(payload)

        self.assertEqual(result, {"keep": "value", "nested": [{}]})
        self.assertIn("env", payload)

    def test_text_diagnostics_redact_environment_assignments(self):
        result = sanitize_text(
            "PATH=C:/sensitive-user-profile\\bin HOME='C:/sensitive-home' detail",
        )
        self.assertNotIn("sensitive-user-profile", result)
        self.assertNotIn("sensitive-home", result)
        self.assertIn("PATH=[REDACTED]", result)
        self.assertIn("HOME=[REDACTED]", result)


if __name__ == "__main__":
    unittest.main()
