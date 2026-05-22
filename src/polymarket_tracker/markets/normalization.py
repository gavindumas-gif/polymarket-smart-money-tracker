from __future__ import annotations


def normalize_outcome(outcome: str | None) -> str | None:
    if outcome is None:
        return None
    normalized = " ".join(outcome.strip().split())
    if normalized.lower() in {"yes", "y"}:
        return "YES"
    if normalized.lower() in {"no", "n"}:
        return "NO"
    return normalized


def normalize_direction(raw_side: str, outcome: str | None) -> str:
    normalized_outcome = normalize_outcome(outcome)
    side = raw_side.upper().strip()
    if side == "BUY":
        if normalized_outcome == "YES":
            return "LONG_YES"
        if normalized_outcome == "NO":
            return "LONG_NO"
        if normalized_outcome:
            return "LONG_OUTCOME"
        return "UNKNOWN"
    if side == "SELL":
        if normalized_outcome == "YES":
            return "SELL_YES"
        if normalized_outcome == "NO":
            return "SELL_NO"
        if normalized_outcome:
            return "SELL_OUTCOME"
        return "UNKNOWN"
    return "UNKNOWN"


def opposite_direction(direction: str) -> str | None:
    return {
        "LONG_YES": "SELL_YES",
        "SELL_YES": "LONG_YES",
        "LONG_NO": "SELL_NO",
        "SELL_NO": "LONG_NO",
        "LONG_OUTCOME": "SELL_OUTCOME",
        "SELL_OUTCOME": "LONG_OUTCOME",
    }.get(direction)
