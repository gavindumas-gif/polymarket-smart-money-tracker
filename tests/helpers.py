from __future__ import annotations

from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
TEMP_ROOT = ROOT / ".test_tmp"
TEMP_ROOT.mkdir(exist_ok=True)


def make_temp_dir() -> Path:
    path = TEMP_ROOT / f"case-{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    return path
