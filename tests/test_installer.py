from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class InstallerEndToEndTestCase(unittest.TestCase):
    def test_local_install_is_offline_idempotent_and_runnable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            runtime = root / "runtime"
            bin_dir = root / "bin"
            command = [
                "sh",
                str(ROOT / "scripts" / "install.sh"),
                "--local",
                "--home",
                str(home),
                "--install-dir",
                str(runtime),
                "--bin-dir",
                str(bin_dir),
                "--python",
                sys.executable,
                "--skip-launch",
                "--no-path-update",
            ]
            first = subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            second = subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            installed = subprocess.run(
                [str(bin_dir / "allpath-agent")],
                input="hello\n/exit\n",
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertIn("Installed command", first.stdout)
        self.assertIn("local starter mode", installed.stdout)
        self.assertIn("Hello! I'm running locally.", installed.stdout)


if __name__ == "__main__":
    unittest.main()
