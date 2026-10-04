"""Package contract loading and ownership of retired global links."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


APP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("learning_runner_contract", APP / "backend/ingest_runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class IngestContractTests(unittest.TestCase):
    def test_package_contract_reaches_both_provider_commands(self):
        with tempfile.TemporaryDirectory() as state:
            url = "https://youtu.be/contract001"
            prompt = runner.build_prompt({"url": url}, state)
            self.assertIn((APP / "skill/SKILL.md").read_text(), prompt)
            self.assertIn(str(APP / "skill/SKILL.md"), prompt)
            self.assertIn(url, prompt)
            self.assertFalse(prompt.startswith("/learning-ingest"))
            for provider in runner.PROVIDERS.PROVIDERS:
                self.assertIn(prompt, provider.build_argv(provider.command, prompt))

    def test_plan_describes_current_execution(self):
        with mock.patch.object(runner.BACKEND, "_open_queue"), \
             mock.patch.object(runner.BACKEND, "_assert_video_available", return_value=(None, None)), \
             mock.patch.object(runner.BACKEND, "anthropic_account_diagnostic", return_value="subscription"):
            plan = runner.BACKEND.create_ingest_plan("https://youtu.be/contract001")
        self.assertEqual(plan["execution"], "앱 적재 계약으로 학습자료 작성")

    def test_upgrade_continues_when_legacy_link_cannot_be_removed(self):
        if os.getuid() == 0:
            self.skipTest("permission denial needs unprivileged uid")
        with tempfile.TemporaryDirectory() as home:
            home = Path(home)
            target = home / ".claude/skills/learning-ingest"
            target.parent.mkdir(parents=True)
            target.symlink_to(home / ".local/share/airlock-learning/skill")
            target.parent.chmod(0o500)
            source = (APP / "install.sh").read_text()
            section = source.split("# --- 5. retire former app-owned global skill links ---", 1)[1].split("# --- 5c.", 1)[0]
            try:
                proc = subprocess.run(["bash", "-c", 'set -e; log() { echo "$*"; }; HERE="$1"; ' + section,
                                       "test", str(APP)], env=dict(os.environ, HOME=str(home)),
                                      text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertTrue(target.is_symlink())
                self.assertIn("could not retire", proc.stdout)
                self.assertEqual(target.parent.stat().st_mode & 0o777, 0o500)
            finally:
                target.parent.chmod(0o700)

    def test_retires_only_owned_links_including_dangling_and_relative(self):
        with tempfile.TemporaryDirectory() as home:
            home = Path(home)
            package = home / ".local/share/airlock-learning/skill"
            owned = home / ".claude/skills/learning-ingest"
            personal = home / ".agents/skills/learning-ingest"
            owned.parent.mkdir(parents=True, mode=0o700)
            personal.mkdir(parents=True)
            personal_file = personal / "SKILL.md"
            personal_file.write_text("personal contract")
            owned.symlink_to(os.path.relpath(package, owned.parent))
            def retire():
                subprocess.run(["bash", str(APP / "deactivate.sh")],
                               env=dict(os.environ, HOME=str(home)), check=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            retire()
            self.assertFalse(owned.is_symlink())
            self.assertEqual(personal_file.read_text(), "personal contract")
            self.assertEqual(owned.parent.stat().st_mode & 0o777, 0o700)
            owned.symlink_to(home / "personal-missing")
            retire()
            self.assertTrue(owned.is_symlink())
            self.assertEqual(personal_file.read_text(), "personal contract")


if __name__ == "__main__":
    unittest.main()
