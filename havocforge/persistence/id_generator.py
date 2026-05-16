from __future__ import annotations

from nanoid import generate


def generate_id(size: int = 12) -> str:
    """Generate a unique URL-safe ID.

    Uses nanoid for generating short, unique, URL-safe identifiers.

    Args:
        size: Length of the ID (default: 12 chars)

    Returns:
        Unique ID string (e.g., "V1StGXR8_Z5j")
    """
    return generate(size=size)
