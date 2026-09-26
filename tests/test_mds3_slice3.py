import inspect
import tempfile
import unittest
from pathlib import Path

from engineering_flow.config import load_config
from engineering_flow.domain import ImplementationProfile, select_implementation_profile
from engineering_flow.orchestrator import CodexImplementationWriter, build_implementation_instruction


class Slice3RoutingTests(unittest.TestCase):
    def test_profile_table_is_deterministic_and_provider_neutral(self):
        expected = {
            ("low", "low"): ImplementationProfile.EFFICIENT,
            ("low", "medium"): ImplementationProfile.BALANCED,
            ("medium", "low"): ImplementationProfile.BALANCED,
            ("medium", "medium"): ImplementationProfile.BALANCED,
            ("high", "low"): ImplementationProfile.STRONG,
            ("low", "high"): ImplementationProfile.STRONG,
            ("high", "high"): ImplementationProfile.STRONG,
        }
        for pair, profile in expected.items():
            self.assertIs(select_implementation_profile(*pair), profile)
        self.assertNotIn("gpt-", inspect.getsource(select_implementation_profile))

    def test_project_config_overrides_packaged_defaults_and_partial_profile_inherits(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / ".git").mkdir()
            # Config loading needs a real worktree; exercise the parser helper
            # through a minimally initialized repository instead.
            import subprocess
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            app = root / ".engineering-flow"; app.mkdir()
            path = app / "config.toml"; path.write_text("""
[provider]
name = "project-codex"
command = "project-codex-bin"
timeout_seconds = 42

[provider.implementation.profiles.balanced]
model = "some-other-model"
""")
            config = load_config(root)
            self.assertEqual(config.implementation_routing(ImplementationProfile.EFFICIENT), ("gpt-5.6-luna", "low"))
            self.assertEqual(config.implementation_routing(ImplementationProfile.BALANCED), ("some-other-model", "medium"))
            self.assertEqual(config.implementation_routing(ImplementationProfile.STRONG), ("gpt-5.6-sol", "medium"))
            self.assertEqual((config.provider_name, config.provider_command, config.timeout_seconds),
                             ("project-codex", "project-codex-bin", 42))
            routed = CodexImplementationWriter(None, config).routing_for(
                type("Task", (), {"complexity": "medium", "risk": "medium"})()
            )
            self.assertEqual(routed, (ImplementationProfile.BALANCED, "some-other-model", "medium"))
            self.assertEqual(config.snapshot["provider"], {
                "name": "project-codex", "command": "project-codex-bin", "timeout_seconds": 42,
                "implementation": {"profiles": {
                    "efficient": {"model": "gpt-5.6-luna", "reasoning": "low"},
                    "balanced": {"model": "some-other-model", "reasoning": "medium"},
                    "strong": {"model": "gpt-5.6-sol", "reasoning": "medium"},
                }},
            })
            self.assertNotIn("gpt-", inspect.getsource(select_implementation_profile))
            self.assertIs(select_implementation_profile("medium", "medium"), ImplementationProfile.BALANCED)

    def test_missing_or_invalid_active_provider_profile_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            import subprocess
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            app = root / ".engineering-flow"; app.mkdir(); path = app / "config.toml"
            cases = (
                '[provider.implementation.profiles.balanced]\nreasoning = "invalid"\n',
                '[provider.implementation.profiles.balanced]\nmodel = "contains whitespace"\n',
                '[provider.implementation.profiles.unknown]\nmodel = "model"\nreasoning = "low"\n',
            )
            for content in cases:
                path.write_text(content)
                with self.assertRaises(Exception):
                    load_config(root)
            # A legacy project config inherits the packaged routing table.
            path.write_text("""[provider]
name = "codex-cli"
command = "codex"
timeout_seconds = 1800

[approval]
prd = "required"
techspec = "required"
task_plan = "required"

[safety]
allow_read_only_planning = true

[execution]
max_review_cycles = 3
allow_workspace_write_development = true
allow_read_only_review = true
""")
            self.assertEqual(load_config(root).implementation_routing(ImplementationProfile.BALANCED),
                             ("gpt-5.6-terra", "medium"))

    def test_prompt_is_task_bounded(self):
        class Feature:
            requirements = ("requirement",); acceptance_criteria = ("feature criterion",)
        class Task:
            id = "T1"; objective = "Add behavior"; requirements = ("task requirement",)
            acceptance_criteria = ("task criterion",); verification = ("python -m unittest",)
            constraints = ("preserve API",); relevant_files = ("src/example.py",)
            existing_patterns = (); depends_on = ()
            def as_payload(self):
                return {"id": self.id, "objective": self.objective, "requirements": list(self.requirements)}
        class Plan: strategy = "small change"
        class Authority:
            feature_contract = Feature(); plan = Plan()
        prompt = build_implementation_instruction(Authority(), Task(), ImplementationProfile.BALANCED)
        for text in ("T1", "Add behavior", "task requirement", "task criterion", "python -m unittest", "src/example.py", "Implement ONLY"):
            self.assertIn(text, prompt)
        for text in ("Do not commit", "Do not choose another task", "Do not touch paths outside", "VERIFIED"):
            self.assertIn(text, prompt)
        self.assertNotIn("choose a Task", prompt)


if __name__ == "__main__":
    unittest.main()
