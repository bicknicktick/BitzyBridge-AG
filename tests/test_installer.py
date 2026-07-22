import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class OneShotInstallerTests(unittest.TestCase):
    def test_root_installer_configures_complete_sandbox_install(self):
        with tempfile.TemporaryDirectory() as td:
            sandbox = Path(td)
            home = sandbox / "home"
            hermes_home = home / ".hermes"
            fake_bin = sandbox / "bin"
            fake_modules = sandbox / "fake-modules"
            command_log = sandbox / "commands.log"

            fake_bin.mkdir(parents=True)
            fake_modules.mkdir()
            (fake_modules / "websocket.py").write_text("# sandbox dependency stub\n", encoding="utf-8")
            home.mkdir(exist_ok=True)
            hermes_home.mkdir()
            (hermes_home / ".env").write_text(
                'TELEGRAM_BOT_TOKEN="test-token-only"\n',
                encoding="utf-8",
            )

            for name in ("hermes", "systemctl"):
                script = fake_bin / name
                script.write_text(
                    "#!/usr/bin/env bash\n"
                    "name=$(basename \"$0\")\n"
                    "printf '%s %s\\n' \"$name\" \"$*\" >> \"$BITZY_COMMAND_LOG\"\n"
                    "if [ \"$name\" = hermes ] && [ \"${BITZY_FAIL_ENABLE:-0}\" = 1 ] "
                    "&& [ \"${1:-}\" = plugins ] && [ \"${2:-}\" = enable ]; then exit 9; fi\n",
                    encoding="utf-8",
                )
                script.chmod(0o755)

            env = os.environ.copy()
            for key in ("TELEGRAM_BOT_TOKEN", "AG_TELEGRAM_USER_ID", "AG_TELEGRAM_CHAT_ID"):
                env.pop(key, None)
            env.update({
                "HOME": str(home),
                "HERMES_HOME": str(hermes_home),
                "PATH": f"{fake_bin}:{env['PATH']}",
                "PYTHONPATH": f"{fake_modules}:{env.get('PYTHONPATH', '')}",
                "BITZY_COMMAND_LOG": str(command_log),
                "AG_TELEGRAM_USER_ID": "123456789",
            })

            result = subprocess.run(
                ["bash", str(REPO_ROOT / "install.sh"), "--non-interactive", "--skip-doctor"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=60,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            plugin = hermes_home / "plugins" / "bitzybridge-ag"
            self.assertTrue((plugin / "plugin.yaml").is_file())
            self.assertTrue((plugin / "watcher.py").is_file())
            skill = hermes_home / "skills" / "automation" / "bitzybridge-ag"
            self.assertTrue((skill / "SKILL.md").is_file())
            self.assertIn("/bitzy", (skill / "SKILL.md").read_text(encoding="utf-8"))

            private_env = home / ".config" / "bitzybridge-ag" / "env"
            self.assertTrue(private_env.is_file())
            self.assertEqual(stat.S_IMODE(private_env.stat().st_mode), 0o600)
            self.assertNotIn("test-token-only", result.stdout + result.stderr)

            service = home / ".config" / "systemd" / "user" / "bitzybridge-ag.service"
            self.assertTrue(service.is_file())
            self.assertIn(
                "%h/.local/share/bitzybridge-ag/venv/bin/python",
                service.read_text(encoding="utf-8"),
            )
            bridge_python = home / ".local" / "share" / "bitzybridge-ag" / "venv" / "bin" / "python"
            self.assertTrue(bridge_python.exists())

            update_env = env.copy()
            update_env["TELEGRAM_BOT_TOKEN"] = "must-not-overwrite"
            update = subprocess.run(
                ["bash", str(REPO_ROOT / "install.sh"), "--non-interactive", "--skip-doctor"],
                cwd=REPO_ROOT,
                env=update_env,
                text=True,
                capture_output=True,
                timeout=60,
            )
            self.assertEqual(update.returncode, 0, update.stdout + update.stderr)
            self.assertIn("test-token-only", private_env.read_text(encoding="utf-8"))
            self.assertNotIn("must-not-overwrite", private_env.read_text(encoding="utf-8"))
            backups = home / ".local" / "share" / "bitzybridge-ag" / "backups"
            self.assertTrue(any(backups.glob("*/plugin/plugin.yaml")))

            marker = plugin / "previous-install.marker"
            marker.write_text("keep me", encoding="utf-8")
            skill_marker = skill / "previous-install.marker"
            skill_marker.write_text("keep skill", encoding="utf-8")
            failing_env = env.copy()
            failing_env["BITZY_FAIL_ENABLE"] = "1"
            failed_update = subprocess.run(
                ["bash", str(REPO_ROOT / "install.sh"), "--non-interactive", "--skip-doctor"],
                cwd=REPO_ROOT,
                env=failing_env,
                text=True,
                capture_output=True,
                timeout=60,
            )
            self.assertNotEqual(failed_update.returncode, 0)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep me")
            self.assertEqual(skill_marker.read_text(encoding="utf-8"), "keep skill")

            commands = command_log.read_text(encoding="utf-8")
            self.assertIn("hermes plugins enable --no-allow-tool-override bitzybridge-ag", commands)
            self.assertIn("systemctl --user enable --now bitzybridge-ag.service", commands)
            self.assertIn("hermes gateway restart", commands)
            self.assertIn("BitzyBridge-AG installed", result.stdout)


if __name__ == "__main__":
    unittest.main()
