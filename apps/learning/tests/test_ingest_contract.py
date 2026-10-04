"""Package contract loading and ownership of retired global links."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


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
