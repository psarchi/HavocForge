"""Simple token-based authentication for API endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Header, status

from havocforge.config import get_config_manager
from server.logging import get_logger

logger = get_logger(__name__)


def get_auth_config() -> dict:
    """Load authentication configuration from server.yaml."""
    try:
        cm = get_config_manager()
        enabled = cm.get_value("server.security.token_auth.enabled", False)
        tokens_str = cm.get_value("server.security.token_auth.tokens", "")

        # Parse comma-separated tokens
        tokens = [t.strip() for t in tokens_str.split(",") if t.strip()]

        return {
            "enabled": enabled,
            "tokens": set(tokens),  # Use set for O(1) lookup
        }
    except Exception as e:
        logger.warning("auth_config_load_failed", error=str(e))
        return {"enabled": False, "tokens": set()}


async def verify_token(
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
) -> str | None:
    """Verify authentication token from Authorization header or X-API-Key header.

    Supports two formats:
    - Authorization: Bearer <token>
    - X-API-Key: <token>

    Args:
        authorization: Authorization header value
        x_api_key: X-API-Key header value

    Returns:
        Token if valid, None otherwise

    Raises:
        HTTPException: If auth is enabled but token is invalid
    """
    config = get_auth_config()

    # If auth is disabled, allow all requests
    if not config["enabled"]:
        return None

    # Extract token from headers
    token = None
    if authorization:
        # Support "Bearer <token>" format
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
        else:
            token = authorization
    elif x_api_key:
        token = x_api_key

    # No token provided
    if not token:
        logger.warning("auth_no_token_provided")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide token via 'Authorization: Bearer <token>' or 'X-API-Key: <token>' header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Validate token
    if token not in config["tokens"]:
        logger.warning(
            "auth_invalid_token", token_prefix=token[:8] if len(token) >= 8 else "short"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid authentication token",
        )

    logger.debug("auth_token_valid", token_prefix=token[:8])
    return token


# Dependency for protected endpoints
RequireAuth = Annotated[str | None, Depends(verify_token)]
