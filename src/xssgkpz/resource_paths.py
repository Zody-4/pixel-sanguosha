"""Read-only assets live in the source tree or PyInstaller's bundle root."""
from pathlib import Path
import sys


RESOURCE_ROOT = (Path(sys._MEIPASS) if getattr(sys, "frozen", False)
                 and hasattr(sys, "_MEIPASS") else Path(__file__).resolve().parents[2])
