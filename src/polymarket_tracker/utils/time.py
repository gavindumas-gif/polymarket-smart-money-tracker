from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_now() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def to_iso(value: object) -> str:
    if value is None:
        return iso_now()
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value), UTC).isoformat().replace("+00:00", "Z")
    text = str(value)
    if text.isdigit():
        return datetime.fromtimestamp(float(text), UTC).isoformat().replace("+00:00", "Z")
    if text.endswith("Z"):
        return text
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC).isoformat().replace("+00:00", "Z")
    except ValueError:
        return iso_now()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
