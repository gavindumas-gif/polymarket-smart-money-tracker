from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class SimpleYamlError(ValueError):
    pass


def load_yaml_file(path: str | Path) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-not-found]

        parsed = yaml.safe_load(text)
        if parsed is None:
            return {}
        if not isinstance(parsed, dict):
            raise SimpleYamlError("YAML root must be a mapping")
        return parsed
    except ModuleNotFoundError:
        return parse_simple_yaml(text)


def parse_simple_yaml(text: str) -> dict[str, Any]:
    lines = _clean_lines(text)
    if not lines:
        return {}
    parsed, index = _parse_block(lines, 0, lines[0][0])
    if index != len(lines):
        raise SimpleYamlError(f"Unexpected trailing YAML at line {lines[index][2]}")
    if not isinstance(parsed, dict):
        raise SimpleYamlError("YAML root must be a mapping")
    return parsed


def _clean_lines(text: str) -> list[tuple[int, str, int]]:
    cleaned: list[tuple[int, str, int]] = []
    for number, raw_line in enumerate(text.splitlines(), start=1):
        if "\t" in raw_line:
            raise SimpleYamlError(f"Tabs are not supported in config YAML at line {number}")
        line = _strip_comment(raw_line).rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        cleaned.append((indent, line.strip(), number))
    return cleaned


def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    for index, char in enumerate(line):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            return line[:index]
    return line


def _parse_block(lines: list[tuple[int, str, int]], index: int, indent: int) -> tuple[Any, int]:
    if index >= len(lines):
        return {}, index
    current_indent, content, _ = lines[index]
    if current_indent < indent:
        return {}, index
    if content.startswith("- "):
        return _parse_list(lines, index, current_indent)
    return _parse_dict(lines, index, current_indent)


def _parse_dict(lines: list[tuple[int, str, int]], index: int, indent: int) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while index < len(lines):
        current_indent, content, line_number = lines[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise SimpleYamlError(f"Unexpected indentation at line {line_number}")
        if content.startswith("- "):
            break
        key, value_text = _split_key_value(content, line_number)
        if value_text == "":
            child, index = _parse_block(lines, index + 1, indent + 2)
            result[key] = child
        else:
            result[key] = _parse_scalar(value_text)
            index += 1
    return result, index


def _parse_list(lines: list[tuple[int, str, int]], index: int, indent: int) -> tuple[list[Any], int]:
    result: list[Any] = []
    while index < len(lines):
        current_indent, content, line_number = lines[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise SimpleYamlError(f"Unexpected list indentation at line {line_number}")
        if not content.startswith("- "):
            break
        item_text = content[2:].strip()
        if item_text == "":
            child, index = _parse_block(lines, index + 1, indent + 2)
            result.append(child)
            continue
        if _looks_like_key_value(item_text):
            key, value_text = _split_key_value(item_text, line_number)
            item: dict[str, Any] = {key: _parse_scalar(value_text) if value_text else {}}
            index += 1
            if index < len(lines) and lines[index][0] > indent:
                child, index = _parse_dict(lines, index, indent + 2)
                item.update(child)
            result.append(item)
        else:
            result.append(_parse_scalar(item_text))
            index += 1
    return result, index


def _looks_like_key_value(text: str) -> bool:
    return bool(re.match(r"^[A-Za-z0-9_\-]+:", text))


def _split_key_value(text: str, line_number: int) -> tuple[str, str]:
    if ":" not in text:
        raise SimpleYamlError(f"Expected key/value mapping at line {line_number}")
    key, value = text.split(":", 1)
    key = key.strip()
    if not key:
        raise SimpleYamlError(f"Empty YAML key at line {line_number}")
    return key, value.strip()


def _parse_scalar(text: str) -> Any:
    if text == "":
        return None
    lowered = text.lower()
    if lowered in {"null", "none", "~"}:
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if text.startswith("[") and text.endswith("]"):
        normalized = re.sub(r"(?<![\"'])\b([A-Za-z_][A-Za-z0-9_\-]*)\b(?![\"'])", r'"\1"', text)
        try:
            return json.loads(normalized)
        except json.JSONDecodeError:
            if text[1:-1].strip() == "":
                return []
            return [_parse_scalar(part.strip()) for part in text[1:-1].split(",")]
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return text[1:-1]
    try:
        if any(char in text for char in [".", "e", "E"]):
            return float(text)
        return int(text)
    except ValueError:
        return text
