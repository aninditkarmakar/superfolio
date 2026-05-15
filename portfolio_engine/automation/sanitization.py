from __future__ import annotations

import re

# Match postgres/postgresql connection URLs including credentials
_POSTGRES_URL_RE = re.compile(
    r"postgres(?:ql)?://[^\s\"']*",
    re.IGNORECASE,
)

# Match key=value assignments for sensitive field names.
# Word boundaries ensure we only match standalone keywords (e.g. "key=", "api_key=")
# and not keywords embedded in compound identifiers (e.g. "primary_key=", "monkey=").
_SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(?:token|password|secret|api_key|key|query_id|flex_query_id|credential|ciphertext|master_key)\b\s*=\s*\S+",
    re.IGNORECASE,
)

# Match amount/nav key=value assignments containing numeric values (including negative)
_FINANCIAL_ASSIGNMENT_RE = re.compile(
    r"(?:amount|nav)\s*=\s*-?[\d.,]+",
    re.IGNORECASE,
)

_PATTERNS = [_POSTGRES_URL_RE, _SECRET_ASSIGNMENT_RE, _FINANCIAL_ASSIGNMENT_RE]
_MAX_LENGTH = 500


def sanitize_error_message(message: str | None) -> str | None:
    """Return a sanitized version of message with sensitive content redacted and length capped."""
    if message is None:
        return None
    result = message
    for pattern in _PATTERNS:
        result = pattern.sub("[redacted]", result)
    return result[:_MAX_LENGTH]
