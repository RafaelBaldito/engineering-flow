"""Redaction helpers for data that may be retained in events or diagnostics."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Iterable

_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?P<prefix>\b(?:api[_-]?key|access[_-]?key|secret|token|password|passwd|"
    r"authorization|credential|private[_-]?key)\b\s*(?:=|:)\s*)"
    r"(?P<quote>[\"']?)(?P<value>[^\s,;}'\"]+)(?P=quote)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_KEY_VALUE = re.compile(r"(?i)\b(?:sk|pk)-[A-Za-z0-9_-]{12,}\b")
_ENVIRONMENT_ASSIGNMENT = re.compile(
    r"(?m)(?<![A-Za-z0-9_])(?P<key>[A-Z][A-Z0-9_]{1,})\s*=\s*"
    r"(?P<quote>[\"']?)(?P<value>[^\s,;}'\"]+)(?P=quote)"
)
_ENVIRONMENT_KEYS = frozenset({"env", "environment"})


def _is_sensitive_key(key: str) -> bool:
    """Identify credential-bearing keys without hiding usage counters.

    Provider responses commonly report usage as fields such as
    ``input_tokens`` and ``cached_input_tokens``.  Those counters are not
    credentials and are required workflow observability metadata.  Treat
    ``token`` as sensitive only when it is a complete key component, leaving
    the plural ``tokens`` counter component intact.
    """

    components = [
        component
        for component in re.split(r"[_\-.]+", key.casefold())
        if component
    ]
    joined = "_".join(components)
    sensitive_components = {
        "secret",
        "token",
        "password",
        "passwd",
        "authorization",
        "credential",
    }
    return (
        any(component in sensitive_components for component in components)
        or "api_key" in joined
        or "access_key" in joined
        or "private_key" in joined
    )


def sanitize_text(value: str, secret_values: Iterable[str] = ()) -> str:
    """Redact exact configured secrets and common credential-shaped values."""

    result = str(value)
    for secret in sorted((s for s in secret_values if s), key=len, reverse=True):
        result = result.replace(secret, "[REDACTED]")
    result = _SENSITIVE_ASSIGNMENT.sub(
        lambda match: f"{match.group('prefix')}[REDACTED]", result
    )
    result = _BEARER.sub("Bearer [REDACTED]", result)
    result = _KEY_VALUE.sub("[REDACTED]", result)
    return _ENVIRONMENT_ASSIGNMENT.sub(
        lambda match: f"{match.group('key')}=[REDACTED]", result
    )


def sanitize(value: Any, secret_values: Iterable[str] = ()) -> Any:
    """Return a JSON-compatible sanitized copy of a diagnostic payload."""

    if isinstance(value, str):
        return sanitize_text(value, secret_values)
    if isinstance(value, Mapping):
        return {
            sanitize_text(str(key), secret_values): (
                "[REDACTED]" if _is_sensitive_key(str(key)) else sanitize(item, secret_values)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize(item, secret_values) for item in value]
    if isinstance(value, set):
        return [sanitize(item, secret_values) for item in sorted(value, key=str)]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return sanitize_text(str(value), secret_values)


def _remove_environment_mappings(value: Any) -> Any:
    """Return a copy without mappings that could expose process environment."""

    if isinstance(value, Mapping):
        return {
            key: _remove_environment_mappings(child)
            for key, child in value.items()
            if str(key).casefold() not in _ENVIRONMENT_KEYS
        }
    if isinstance(value, (list, tuple, set)):
        return [_remove_environment_mappings(child) for child in value]
    return value


def sanitize_payload(payload: Mapping[str, Any], secret_values: Iterable[str] = ()) -> dict[str, Any]:
    sanitized = sanitize(_remove_environment_mappings(payload), secret_values)
    return sanitized if isinstance(sanitized, dict) else {"value": sanitized}


def sanitize_configuration_snapshot(
    value: Mapping[str, Any], secret_values: Iterable[str] = ()
) -> dict[str, Any]:
    """Sanitize persisted configuration without retaining environment mappings."""

    sanitized = sanitize(_remove_environment_mappings(value), secret_values)
    return sanitized if isinstance(sanitized, dict) else {"value": sanitized}
