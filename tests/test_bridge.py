import importlib.util
from enum import Enum
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR))


class BridgeContractTests(unittest.TestCase):
    def setUp(self):
        import bridge
        self.bridge = bridge

    def test_detects_antigravity_write_permission_prompt(self):
        ocr = """
        Allow write access to this path?
        /home/example/project/file.txt
        1 Yes, allow this time
        2 Yes, and always allow in this project
        3 Yes, and always allow
        4 No (tell the agent what to do instead)
        """
        prompt = self.bridge.detect_permission_prompt(ocr)
        self.assertIsNotNone(prompt)
        self.assertEqual(prompt["kind"], "write")
        self.assertIn("/home/example/project/file.txt", prompt["detail"])

    def test_rejects_normal_antigravity_screen_without_modal(self):
        self.assertIsNone(self.bridge.detect_permission_prompt("Agent Manager Inbox Send message"))

    def test_reply_button_round_trip(self):
        label = self.bridge.make_button_label("A1B2C3", 2)
        self.assertEqual(self.bridge.parse_button_label(label), {"nonce": "A1B2C3", "choice": 2})

    def test_rejects_mismatched_choice_and_label(self):
        self.assertIsNone(self.bridge.parse_button_label("AG A1B2C3 · 1 Deny"))
        self.assertIsNone(self.bridge.parse_button_label("AG A1B2C3 · 4 Allow once"))

    def test_rejects_free_text_that_is_not_bridge_button(self):
        self.assertIsNone(self.bridge.parse_button_label("2 yes allow it"))

    def test_atomic_decision_is_single_use(self):
        with tempfile.TemporaryDirectory() as td:
            first = self.bridge.write_decision(Path(td), "A1B2C3", 1)
            second = self.bridge.write_decision(Path(td), "A1B2C3", 4)
            self.assertTrue(first)
            self.assertFalse(second)
            payload = json.loads((Path(td) / "A1B2C3.json").read_text())
            self.assertEqual(payload["choice"], 1)

    def test_pending_request_is_written_once_and_private(self):
        with tempfile.TemporaryDirectory() as td:
            pending = Path(td)
            request = {
                "nonce": "A1B2C3", "created_at": time.time(),
                "expires_at": time.time() + 300,
                "chat_id": "123456789", "user_id": "123456789",
                "fingerprint": "f" * 64,
            }
            self.assertTrue(self.bridge.write_pending(pending, request))
            self.assertFalse(self.bridge.write_pending(pending, request))
            self.assertEqual((pending / "A1B2C3.json").stat().st_mode & 0o777, 0o600)

    def test_queue_rejects_nonce_without_pending_prompt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            result = self.bridge.queue_decision(
                root / "pending", root / "responses", "A1B2C3", 1,
                chat_id="123456789", user_id="123456789",
            )
            self.assertEqual(result, "missing")
            self.assertFalse((root / "responses" / "A1B2C3.json").exists())

    def test_queue_rejects_expired_pending_prompt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.bridge.write_pending(root / "pending", {
                "nonce": "A1B2C3", "created_at": 1, "expires_at": 2,
                "chat_id": "123456789", "user_id": "123456789",
                "fingerprint": "f" * 64,
            })
            result = self.bridge.queue_decision(
                root / "pending", root / "responses", "A1B2C3", 1,
                chat_id="123456789", user_id="123456789", now=3,
            )
            self.assertEqual(result, "expired")

    def test_queue_binds_decision_to_sender_and_fingerprint(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fingerprint = "a" * 64
            self.bridge.write_pending(root / "pending", {
                "nonce": "A1B2C3", "created_at": 1, "expires_at": 100,
                "chat_id": "123456789", "user_id": "123456789",
                "fingerprint": fingerprint,
            })
            wrong = self.bridge.queue_decision(
                root / "pending", root / "responses", "A1B2C3", 1,
                chat_id="123456789", user_id="999", now=2,
            )
            self.assertEqual(wrong, "unauthorized")
            accepted = self.bridge.queue_decision(
                root / "pending", root / "responses", "A1B2C3", 2,
                chat_id="123456789", user_id="123456789", now=2,
            )
            self.assertEqual(accepted, "accepted")
            payload = json.loads((root / "responses" / "A1B2C3.json").read_text())
            self.assertEqual(payload["fingerprint"], fingerprint)


class PluginHookTests(unittest.TestCase):
    def _load_plugin(self):
        spec = importlib.util.spec_from_file_location("ag_telegram_plugin", PLUGIN_DIR / "__init__.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _pending(plugin, nonce="A1B2C3"):
        import bridge
        bridge.write_pending(plugin.PENDING_DIR, {
            "nonce": nonce, "created_at": time.time(), "expires_at": time.time() + 300,
            "chat_id": "123456789", "user_id": "123456789", "fingerprint": "f" * 64,
        })

    def test_hook_fails_closed_when_identity_is_not_configured(self):
        plugin = self._load_plugin()
        plugin.ALLOWED_CHAT_ID = ""
        plugin.ALLOWED_USER_ID = ""

        class Event:
            text = "AG A1B2C3 · 1 Allow once"
            source = None

        result = plugin.handle_gateway_message(Event())
        self.assertEqual(result, {"action": "skip", "reason": "bitzybridge-ag-misconfigured"})

    def test_hook_intercepts_authorized_telegram_button(self):
        plugin = self._load_plugin()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plugin.PENDING_DIR = root / "pending"
            plugin.RESPONSE_DIR = root / "responses"
            plugin.ALLOWED_CHAT_ID = "123456789"
            plugin.ALLOWED_USER_ID = "123456789"
            self._pending(plugin)

            class Source:
                platform = "telegram"
                chat_id = "123456789"
                user_id = "123456789"

            class Event:
                text = "AG A1B2C3 · 1 Allow once"
                source = Source()

            result = plugin.handle_gateway_message(Event())
            self.assertEqual(result["action"], "skip")
            self.assertEqual(result["reason"], "bitzybridge-ag-accepted")
            self.assertTrue((plugin.RESPONSE_DIR / "A1B2C3.json").exists())

    def test_hook_accepts_real_hermes_platform_enum(self):
        class Platform(Enum):
            TELEGRAM = "telegram"

        plugin = self._load_plugin()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plugin.PENDING_DIR = root / "pending"
            plugin.RESPONSE_DIR = root / "responses"
            plugin.ALLOWED_CHAT_ID = "123456789"
            plugin.ALLOWED_USER_ID = "123456789"
            self._pending(plugin)

            class Source:
                platform = Platform.TELEGRAM
                chat_id = "123456789"
                user_id = "123456789"

            class Event:
                text = "AG A1B2C3 · 1 Allow once"
                source = Source()

            result = plugin.handle_gateway_message(Event())
            self.assertEqual(result["reason"], "bitzybridge-ag-accepted")

    def test_plugin_honors_isolated_state_directory_from_environment(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch.dict(os.environ, {"AG_STATE_DIR": str(root)}):
                plugin = self._load_plugin()
            self.assertEqual(plugin.PENDING_DIR, root / "pending")
            self.assertEqual(plugin.RESPONSE_DIR, root / "responses")

    def test_hook_rejects_same_text_from_wrong_chat(self):
        plugin = self._load_plugin()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plugin.PENDING_DIR = root / "pending"
            plugin.RESPONSE_DIR = root / "responses"
            plugin.ALLOWED_CHAT_ID = "123456789"
            plugin.ALLOWED_USER_ID = "123456789"
            self._pending(plugin)

            class Source:
                platform = "telegram"
                chat_id = "999"
                user_id = "999"

            class Event:
                text = "AG A1B2C3 · 4 Deny"
                source = Source()

            result = plugin.handle_gateway_message(Event())
            self.assertEqual(result["action"], "skip")
            self.assertEqual(result["reason"], "bitzybridge-ag-unauthorized")
            self.assertFalse((plugin.RESPONSE_DIR / "A1B2C3.json").exists())

    def test_hook_rejects_button_without_pending_prompt(self):
        plugin = self._load_plugin()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plugin.PENDING_DIR = root / "pending"
            plugin.RESPONSE_DIR = root / "responses"
            plugin.ALLOWED_CHAT_ID = "123456789"
            plugin.ALLOWED_USER_ID = "123456789"

            class Source:
                platform = "telegram"
                chat_id = "123456789"
                user_id = "123456789"

            class Event:
                text = "AG A1B2C3 · 3 Always allow"
                source = Source()

            result = plugin.handle_gateway_message(Event())
            self.assertEqual(result["action"], "skip")
            self.assertEqual(result["reason"], "bitzybridge-ag-missing")
            self.assertFalse((plugin.RESPONSE_DIR / "A1B2C3.json").exists())

    def test_registers_control_tool_and_gateway_hook(self):
        plugin = self._load_plugin()

        class Context:
            def __init__(self):
                self.tools = []
                self.hooks = []
                self.commands = []
                self.dispatched = []

            def register_tool(self, **kwargs):
                self.tools.append(kwargs)

            def register_hook(self, name, handler):
                self.hooks.append((name, handler))

            def register_command(self, **kwargs):
                self.commands.append(kwargs)

            def dispatch_tool(self, name, args):
                self.dispatched.append((name, args))
                if args == {"action": "status"}:
                    return (
                        '{"ok":true,"reason":"status","ready":true,"busy":false,'
                        '"conversation":"AG_BRIDGE_E2E_OK","url":"https://127.0.0.1:43213/c/demo",'
                        '"target_id":"INTERNAL","composer_text":"",'
                        '"send_disabled":true,"latest_text":"Running tests\\n  and preparing final output."}'
                    )
                return '{"ok": true}'

        ctx = Context()
        plugin.register(ctx)
        self.assertEqual([item["name"] for item in ctx.tools], ["antigravity_control"])
        self.assertEqual([item[0] for item in ctx.hooks], ["pre_gateway_dispatch"])
        self.assertEqual([item["name"] for item in ctx.commands], ["bitzy"])
        self.assertEqual(ctx.commands[0]["args_hint"], "")

        handler = ctx.commands[0]["handler"]
        self.assertIn("/bitzy status", handler(""))
        self.assertIn("/skill bitzybridge-ag", handler("help"))
        status = handler("status")
        self.assertIn("**BitzyBridge-AG Status**", status)
        self.assertIn("🟢 **Ready**", status)
        self.assertIn("**Conversation:** `AG_BRIDGE_E2E_OK`", status)
        self.assertIn("**Composer:** Empty", status)
        self.assertIn("> Running tests and preparing final output.", status)
        self.assertIn("[Open conversation](https://127.0.0.1:43213/c/demo)", status)
        self.assertNotIn("target_id", status)
        self.assertNotIn('{"ok"', status)
        noisy_status = plugin._format_status(
            {
                "ok": True,
                "ready": True,
                "busy": False,
                "conversation": "AG_BRIDGE_E2E_OK",
                "composer_text": "",
                "latest_text": "sidebar noise " * 100,
            }
        )
        self.assertNotIn("Latest activity", noisy_status)
        self.assertNotIn("sidebar noise", noisy_status)
        self.assertEqual(
            ctx.dispatched[-1],
            ("antigravity_control", {"action": "status"}),
        )

        self.assertEqual(handler("stop Exact Conversation"), '{"ok": true}')
        self.assertEqual(
            ctx.dispatched[-1],
            (
                "antigravity_control",
                {"action": "stop", "expected_conversation": "Exact Conversation"},
            ),
        )

        self.assertEqual(handler("send Exact Conversation :: Fix the tests"), '{"ok": true}')
        self.assertEqual(
            ctx.dispatched[-1],
            (
                "antigravity_control",
                {
                    "action": "send",
                    "expected_conversation": "Exact Conversation",
                    "task": "Fix the tests",
                },
            ),
        )
        before = len(ctx.dispatched)
        self.assertIn("Usage", handler("send malformed"))
        self.assertEqual(len(ctx.dispatched), before)


if __name__ == "__main__":
    unittest.main()
