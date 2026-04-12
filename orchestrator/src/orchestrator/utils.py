from __future__ import annotations

from datetime import UTC, datetime
import json
import re
from uuid import uuid4


LABEL_PART_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9._-]{0,61}[a-zA-Z0-9])?$")


def short_id(prefix: str = "") -> str:
    value = uuid4().hex[:8]
    return f"{prefix}{value}" if prefix else value


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def validate_metadata_key(key: str) -> None:
    if not key:
        raise ValueError("metadata key cannot be empty")
    if len(key) > 63:
        raise ValueError(f"metadata key '{key}' is too long (max 63 characters)")
    if not LABEL_PART_RE.match(key):
        raise ValueError(
            f"metadata key '{key}' contains invalid characters. Must start/end with alphanumeric "
            "and contain only alphanumeric, '-', '_', or '.'"
        )


def is_valid_label_part(value: str) -> bool:
    return bool(value) and len(value) <= 63 and bool(LABEL_PART_RE.match(value))


def parse_env_list(values: list[str]) -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = []
    for item in values:
        if not item:
            continue
        if "=" in item:
            key, value = item.split("=", 1)
        else:
            key, value = item, ""
        parsed.append((key.strip(), value))
    return parsed


def json_dumps(data: object) -> str:
    return json.dumps(data, ensure_ascii=True, separators=(",", ":"))
