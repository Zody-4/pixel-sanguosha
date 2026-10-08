"""Run the formal source build directly without installing the project package."""

from __future__ import annotations

import sys
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from xssgkpz.app import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

