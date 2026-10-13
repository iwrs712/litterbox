from __future__ import annotations

import secrets


def normalize_configured_token(token: str | None) -> str:
    return (token or "").strip()


def extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.strip().split(None, 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None


def is_http_authorized(expected_token: str, authorization_header: str | None) -> bool:
    configured = normalize_configured_token(expected_token)
    if not configured:
        return True
    provided = extract_bearer_token(authorization_header)
    if not provided:
        return False
    return secrets.compare_digest(provided, configured)


def is_e2b_authorized(
    expected_key: str,
    api_key_header: str | None,
    authorization_header: str | None,
    access_token_header: str | None = None,
) -> bool:
    configured = normalize_configured_token(expected_key)
    if not configured:
        return True
    provided = (
        (api_key_header or "").strip()
        or (access_token_header or "").strip()
        or extract_bearer_token(authorization_header)
    )
    return bool(provided) and secrets.compare_digest(provided, configured)
