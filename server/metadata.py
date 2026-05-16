from typing import Any

from havocforge.context import GenContext


def build_response_with_metadata(
    items: list,
    context: GenContext,
    chaos_results: list[str] | None = None,
    include_metadata: bool = False,
) -> dict[str, Any]:
    """Build API response with optional metadata.

    Args:
        items: Generated items to include in response.
        context: Generation context containing seed, schema, etc.
        chaos_results: List of chaos operation descriptions that were applied.
        include_metadata: Whether to include _metadata field in response.

    Returns:
        dict: Response with items and optional _metadata field.

    Example:
        >>> response = build_response_with_metadata(
        ...     items=[{"id": 1}, {"id": 2}],
        ...     context=ctx,
        ...     chaos_results=["late_arrival"],
        ...     include_metadata=True
        ... )
        >>> response.keys()
        dict_keys(['items', '_metadata'])
    """
    response: dict[str, Any] = {"items": items}

    if include_metadata:
        metadata = context.build_meta()
        metadata["count"] = len(items)
        metadata["chaos_applied"] = chaos_results or []
        response["_metadata"] = metadata

    return response
