from __future__ import annotations

import hashlib
import json
from typing import Any


def dumps(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def pretty(data: Any) -> str:
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=True)


def loads(text: str | None, default: Any = None) -> Any:
    if text is None:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def stable_hash(data: Any) -> str:
    return hashlib.sha256(dumps(data).encode("utf-8")).hexdigest()
