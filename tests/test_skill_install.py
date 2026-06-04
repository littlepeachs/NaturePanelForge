from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class SkillInstallTests(unittest.TestCase):
    def test_install_skills_uses_codex_home_and_copies_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "CODEX_HOME": str(Path(tmp) / "codex_home")}
            result = subprocess.run(
                ["bash", "scripts/install_skills.sh"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            installed = Path(tmp) / "codex_home" / "skills" / "codex-panel-reproduce" / "SKILL.md"
            self.assertTrue(installed.exists())
            text = installed.read_text(encoding="utf-8")
            self.assertIn("name: codex-panel-reproduce", text)
            self.assertIn("reproduce_panel.py", text)

    def test_install_skills_dry_run_does_not_create_destination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / "codex_home"
            env = {**os.environ, "CODEX_HOME": str(codex_home), "DRY_RUN": "1"}
            result = subprocess.run(
                ["bash", "scripts/install_skills.sh"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Would install codex-panel-reproduce", result.stdout)
            self.assertFalse(codex_home.exists())


if __name__ == "__main__":
    unittest.main()
