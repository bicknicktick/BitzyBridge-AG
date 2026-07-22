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


class WatcherPortRotationTests(unittest.TestCase):
    def test_refreshes_cdp_port_after_antigravity_restart(self):
        import watcher

        with (
            patch.object(watcher, "discover_cdp_port", return_value=44201),
            patch.object(watcher, "inspect_prompt", return_value=None) as inspect,
        ):
            port, prompt = watcher.inspect_prompt_with_refresh(43625)

        self.assertEqual(port, 44201)
        self.assertIsNone(prompt)
        inspect.assert_called_once_with(44201)

    def test_recovers_matching_unexpired_pending_after_restart(self):
        import watcher

        with tempfile.TemporaryDirectory() as temp:
            pending_dir = Path(temp)
            payload = {
                "nonce": "B3C7FE",
                "created_at": time.time() - 10,
                "expires_at": time.time() + 240,
                "chat_id": "123456789",
                "user_id": "123456789",
                "fingerprint": "e" * 64,
                "target_id": "PAGE1",
                "title": "Allow write access to this path?",
                "detail": "",
            }
            path = pending_dir / "B3C7FE.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            path.chmod(0o600)
            with (
                patch.dict(os.environ, {
                    "AG_TELEGRAM_CHAT_ID": "123456789",
                    "AG_TELEGRAM_USER_ID": "123456789",
                }),
                patch.object(watcher, "PENDING_DIR", pending_dir),
            ):
                recovered = watcher.recover_pending({"fingerprint": "e" * 64})

        self.assertEqual(recovered, payload)


if __name__ == "__main__":
    unittest.main()
