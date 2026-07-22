import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR))


class CDPContractTests(unittest.TestCase):
    def setUp(self):
        import cdp_client
        self.cdp = cdp_client

    def test_validates_complete_four_choice_prompt(self):
        raw = {
            "title": "Allow write access to this path?",
            "detail": "/home/example/PROJECTS/demo",
            "choices": {
                "1": "Yes, allow this time",
                "2": "Yes, and always allow in this project",
                "3": "Yes, and always allow",
                "4": "No (tell the agent what to do instead)",
            },
            "target_id": "PAGE1",
            "url": "https://127.0.0.1:46359/c/abc",
        }
        prompt = self.cdp.validate_snapshot(raw)
        self.assertEqual(prompt["kind"], "write")
        self.assertEqual(prompt["detail"], "/home/example/PROJECTS/demo")
        self.assertEqual(len(prompt["fingerprint"]), 64)

    def test_rejects_prompt_missing_one_choice(self):
        raw = {
            "title": "Allow write access to this path?",
            "detail": "/tmp/x",
            "choices": {"1": "Yes, allow this time", "2": "project", "3": "always"},
            "target_id": "PAGE1", "url": "https://127.0.0.1:46359/x",
        }
        self.assertIsNone(self.cdp.validate_snapshot(raw))

    def test_fingerprint_changes_when_target_changes(self):
        base = {
            "title": "Allow write access to this path?", "detail": "/tmp/x",
            "choices": {
                "1": "Yes, allow this time", "2": "Yes, and always allow in this project",
                "3": "Yes, and always allow", "4": "No",
            },
            "target_id": "PAGE1", "url": "https://127.0.0.1:46359/x",
        }
        first = self.cdp.validate_snapshot(base)
        second = self.cdp.validate_snapshot({**base, "target_id": "PAGE2"})
        self.assertNotEqual(first["fingerprint"], second["fingerprint"])

    def test_current_radio_prompt_selects_label_then_submits(self):
        self.assertIn("[tabindex],label", self.cdp._FIND_PERMISSION_JS)
        self.assertIn(".startsWith('submit')", self.cdp._FIND_PERMISSION_JS)
        prompt = self.cdp.validate_snapshot({
            "title": "Allow write access to this path?",
            "detail": "",
            "choices": {
                "1": "1 Yes, allow this time",
                "2": "2 Yes, and always allow in this project",
                "3": "3 Yes, and always allow",
                "4": "4 No",
            },
            "target_id": "PAGE1",
            "url": "https://127.0.0.1:46359/c/abc",
        })
        self.assertIsNotNone(prompt)
        expression = self.cdp.build_apply_choice_js(
            {"title": "Allow write access to this path?", "detail": ""}, 1
        )
        self.assertIn("element.click()", expression)
        self.assertNotIn("requestAnimationFrame", expression)
        self.assertNotIn("new Promise", expression)
        self.assertIn("submit.click()", expression)
        self.assertLess(expression.index("element.click()"), expression.index("submit.click()"))


class PolicyTests(unittest.TestCase):
    def setUp(self):
        import policy
        self.policy = policy

    def test_scoped_bypass_allows_project_path_without_global_choice(self):
        cfg = {
            "mode": "scoped-bypass",
            "auto_choice": 2,
            "allowed_kinds": ["write"],
            "allow_roots": ["/home/example/PROJECTS"],
            "deny_roots": ["/home/example/.ssh"],
        }
        result = self.policy.decide(cfg, {
            "kind": "write", "detail": "/home/example/PROJECTS/demo/app.py"
        })
        self.assertEqual(result, 2)

    def test_scoped_bypass_refuses_path_prefix_collision(self):
        cfg = {
            "mode": "scoped-bypass", "auto_choice": 2,
            "allowed_kinds": ["write"], "allow_roots": ["/home/example/PROJECTS"],
            "deny_roots": [],
        }
        self.assertIsNone(self.policy.decide(cfg, {
            "kind": "write", "detail": "/home/example/PROJECTS-evil/file"
        }))

    def test_sensitive_root_is_auto_denied(self):
        cfg = {
            "mode": "scoped-bypass", "auto_choice": 2,
            "allowed_kinds": ["write"], "allow_roots": ["/home/example"],
            "deny_roots": ["/home/example/.ssh"],
        }
        self.assertEqual(self.policy.decide(cfg, {
            "kind": "write", "detail": "/home/example/.ssh/config"
        }), 4)

    def test_never_auto_selects_global_always_allow(self):
        cfg = {
            "mode": "scoped-bypass", "auto_choice": 3,
            "allowed_kinds": ["write"], "allow_roots": ["/home/example/PROJECTS"],
            "deny_roots": [],
        }
        self.assertIsNone(self.policy.decide(cfg, {
            "kind": "write", "detail": "/home/example/PROJECTS/demo"
        }))

    def test_remote_confirm_never_auto_allows_normal_path(self):
        cfg = {
            "mode": "remote-confirm", "auto_choice": 2,
            "allowed_kinds": ["write"], "allow_roots": ["/home/example/PROJECTS"],
            "deny_roots": [],
        }
        self.assertIsNone(self.policy.decide(cfg, {
            "kind": "write", "detail": "/home/example/PROJECTS/demo"
        }))


if __name__ == "__main__":
    unittest.main()
