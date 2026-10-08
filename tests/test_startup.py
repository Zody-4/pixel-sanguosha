from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest

from _support import PROJECT_ROOT


class InternalShellStartupTests(unittest.TestCase):
    def test_formal_launcher_draws_internal_shell_and_exits(self) -> None:
        with tempfile.TemporaryDirectory(prefix="xssgkpz-startup-") as data_root:
            environment = os.environ.copy()
            environment["LOCALAPPDATA"] = data_root
            environment["SDL_VIDEODRIVER"] = "dummy"
            environment["SDL_AUDIODRIVER"] = "dummy"
            completed = subprocess.run(
                [sys.executable, str(PROJECT_ROOT / "run_game.py"), "--smoke-test"],
                cwd=PROJECT_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
