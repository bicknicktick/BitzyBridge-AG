import json
import sys
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR))


class ControlContractTests(unittest.TestCase):
    def setUp(self):
        import cdp_control
        self.control = cdp_control

    def test_validates_unique_loopback_control_surface(self):
        raw = {
            "target_id": "PAGE1",
            "url": "https://127.0.0.1:46359/c/abc",
            "title": "bot vps",
            "composer_count": 1,
            "send_count": 1,
            "stop_count": 0,
            "composer_text": "",
            "latest_text": "Done",
        }
        state = self.control.validate_control_snapshot(raw)
        self.assertTrue(state["ready"])
        self.assertFalse(state["busy"])
        self.assertEqual(state["conversation"], "bot vps")

    def test_validates_busy_surface_where_stop_replaces_send(self):
        raw = {
            "target_id": "PAGE1",
            "url": "https://127.0.0.1:46359/c/abc",
            "title": "bot vps",
            "composer_count": 1,
            "send_count": 0,
            "stop_count": 1,
            "composer_text": "",
            "latest_text": "Working...",
        }
        state = self.control.validate_control_snapshot(raw)
        self.assertTrue(state["ready"])
        self.assertTrue(state["busy"])

    def test_rejects_ambiguous_or_nonloopback_surface(self):
        base = {
            "target_id": "PAGE1", "url": "https://127.0.0.1:46359/c/abc",
            "title": "bot vps", "composer_count": 1, "send_count": 1,
            "stop_count": 0, "composer_text": "", "latest_text": "",
        }
        self.assertIsNone(self.control.validate_control_snapshot({**base, "composer_count": 2}))
        self.assertIsNone(self.control.validate_control_snapshot({**base, "url": "https://example.com/c/abc"}))

    def test_normalizes_task_without_changing_content(self):
        task = "Fix failing tests\nRun the real suite"
        self.assertEqual(self.control.normalize_task(task), task)

    def test_rejects_empty_or_oversized_task(self):
        with self.assertRaises(ValueError):
            self.control.normalize_task("   ")
        with self.assertRaises(ValueError):
            self.control.normalize_task("x" * 20001)

    def test_selects_exact_expected_conversation_from_multiple_windows(self):
        states = [
            {"conversation": "bot vps", "target_id": "A"},
            {"conversation": "AG Bridge E2E Fixture", "target_id": "B"},
        ]
        selected = self.control.select_control_state(states, "AG Bridge E2E Fixture")
        self.assertEqual(selected["target_id"], "B")
        with self.assertRaises(RuntimeError):
            self.control.select_control_state(states, None)

    def test_lexical_insert_uses_single_native_input_path(self):
        expression = self.control.build_insert_text_js("AG_BRIDGE_E2E_OK")
        self.assertEqual(expression.count("execCommand('insertText'"), 1)
        self.assertNotIn("dispatchEvent(new InputEvent", expression)
        self.assertNotIn("ok:commandOk", expression)
        self.assertIn("ok:true", expression)

    def test_waits_for_lexical_async_commit(self):
        from unittest.mock import patch

        responses = iter(["\n", "AG_BRIDGE_E2E_OK"])
        with patch.object(self.control, "_evaluate", side_effect=lambda *_: next(responses)):
            self.assertTrue(
                self.control.wait_for_composer_text(
                    "ws://127.0.0.1:1234/devtools/page/test",
                    "AG_BRIDGE_E2E_OK",
                    timeout=0.1,
                    poll_interval=0,
                )
            )


class ToolHandlerTests(unittest.TestCase):
    def test_invalid_action_is_fail_closed(self):
        import tool_handlers
        payload = json.loads(tool_handlers.antigravity_control({"action": "destroy"}))
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["reason"], "invalid-action")

    def test_send_requires_task(self):
        import tool_handlers
        payload = json.loads(tool_handlers.antigravity_control({"action": "send"}))
        self.assertFalse(payload["ok"])
        self.assertIn("task", payload["reason"])


if __name__ == "__main__":
    unittest.main()
