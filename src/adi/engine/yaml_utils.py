"""Small YAML subset loader/dumper to avoid heavy dependencies.

Supports mappings, lists, and scalar values used by ADI artifacts/config.
"""

from __future__ import annotations

import json
import re
from typing import Any

_INT_RE = re.compile(r"^-?[0-9]+$")
_FLOAT_RE = re.compile(r"^-?[0-9]+\.[0-9]+$")
_SAFE_STRING_RE = re.compile(r"^[A-Za-z0-9_./-]+$")


def load_yaml(text: str) -> Any:
    """Parse YAML-like text into Python values."""
    raw = text.strip()
    if not raw:
        return {}

    # JSON is valid YAML. Try this first for robustness.
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    lines = _normalized_lines(text)
    if not lines:
        return {}

    value, index = _parse_node(lines, 0, lines[0][0])
    if index != len(lines):
        raise ValueError("Unexpected trailing YAML content")
    return value


def dump_yaml(data: Any) -> str:
    """Serialize Python values to YAML-like text."""
    rendered = _dump_node(data, indent=0).rstrip()
    return f"{rendered}\n" if rendered else ""


def _normalized_lines(text: str) -> list[tuple[int, str]]:
    items: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        if raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        items.append((indent, stripped))
    return items


def _parse_node(
    lines: list[tuple[int, str]],
    index: int,
    indent: int,
) -> tuple[Any, int]:
    if index >= len(lines):
        return {}, index
    current_indent, token = lines[index]
    if current_indent < indent:
        return {}, index
    if token in {"{}", "[]"}:
        return _parse_scalar(token), index + 1
    if token.startswith("- ") or token == "-":
        return _parse_list(lines, index, current_indent)
    return _parse_map(lines, index, current_indent)


def _parse_map(
    lines: list[tuple[int, str]],
    index: int,
    indent: int,
) -> tuple[dict[str, Any], int]:
    output: dict[str, Any] = {}
    i = index
    while i < len(lines):
        current_indent, token = lines[i]
        if current_indent < indent:
            break
        if current_indent != indent:
            raise ValueError("Invalid indentation in YAML mapping")
        if token.startswith("- ") or token == "-":
            break
        if ":" not in token:
            raise ValueError("Invalid mapping entry")
        key, rest = token.split(":", 1)
        key = key.strip()
        rest = rest.strip()
        i += 1
        if rest:
            output[key] = _parse_scalar(rest)
            continue
        if i < len(lines) and lines[i][0] > indent:
            child, i = _parse_node(lines, i, lines[i][0])
            output[key] = child
        else:
            output[key] = {}
    return output, i


def _parse_list(
    lines: list[tuple[int, str]],
    index: int,
    indent: int,
) -> tuple[list[Any], int]:
    output: list[Any] = []
    i = index
    while i < len(lines):
        current_indent, token = lines[i]
        if current_indent < indent:
            break
        if current_indent != indent:
            raise ValueError("Invalid indentation in YAML list")
        if not (token.startswith("- ") or token == "-"):
            break
        rest = token[2:].strip() if token.startswith("- ") else ""
        i += 1
        if rest:
            output.append(_parse_scalar(rest))
            continue
        if i < len(lines) and lines[i][0] > indent:
            child, i = _parse_node(lines, i, lines[i][0])
            output.append(child)
        else:
            output.append(None)
    return output, i


def _parse_scalar(value: str) -> Any:
    lower = value.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if lower in {"null", "~"}:
        return None
    if _INT_RE.match(value):
        try:
            return int(value)
        except ValueError:
            pass
    if _FLOAT_RE.match(value):
        try:
            return float(value)
        except ValueError:
            pass
    if value.startswith("'") and value.endswith("'") and len(value) >= 2:
        return value[1:-1].replace("''", "'")
    if value.startswith('"') and value.endswith('"') and len(value) >= 2:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value[1:-1]
    if value.startswith("[") or value.startswith("{"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass
    return value


def _dump_node(value: Any, indent: int) -> str:
    prefix = " " * indent
    if isinstance(value, dict):
        if not value:
            return f"{prefix}{{}}"
        lines: list[str] = []
        for key, item in value.items():
            if _is_scalar(item):
                lines.append(f"{prefix}{key}: {_format_scalar(item)}")
            else:
                nested = _dump_node(item, indent + 2)
                lines.append(f"{prefix}{key}:")
                lines.append(nested)
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return f"{prefix}[]"
        lines = []
        for item in value:
            if _is_scalar(item):
                lines.append(f"{prefix}- {_format_scalar(item)}")
            else:
                lines.append(f"{prefix}-")
                lines.append(_dump_node(item, indent + 2))
        return "\n".join(lines)
    return f"{prefix}{_format_scalar(value)}"


def _is_scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool)) or value is None


def _format_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if not isinstance(value, str):
        return _quote_string(str(value))
    if not value:
        return "''"
    if "\n" in value:
        return json.dumps(value)
    lower = value.lower()
    if lower in {"true", "false", "null", "~"} or _INT_RE.match(value) or _FLOAT_RE.match(value):
        return _quote_string(value)
    if _SAFE_STRING_RE.match(value):
        return value
    return _quote_string(value)


def _quote_string(value: str) -> str:
    escaped = value.replace("'", "''")
    return f"'{escaped}'"
