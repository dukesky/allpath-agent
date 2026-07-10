from __future__ import annotations

import compileall
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
TESTS = ROOT / "tests"


def main() -> int:
    sys.path.insert(0, str(SOURCE))
    compiled = compileall.compile_dir(SOURCE, quiet=1) and compileall.compile_dir(TESTS, quiet=1)
    if not compiled:
        print("Python compilation failed", file=sys.stderr)
        return 1

    suite = unittest.defaultTestLoader.discover(str(TESTS))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
