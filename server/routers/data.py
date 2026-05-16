from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from havocforge.persistence import StorageManager
from server.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/v1", tags=["data"])


@router.get("/data")
async def list_datasets(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(50, ge=1, le=100, description="Items per page"),
) -> JSONResponse:
    """List all persisted datasets with pagination.

    Queries PostgreSQL (primary storage) and includes recent Redis data.
    For full dataset items, use GET /data/{id}/items

    Args:
        page: Page number (1-indexed)
        limit: Number of datasets per page (max 100)

    Returns:
        Paginated list of dataset metadata
    """
    storage = StorageManager()
    await storage.connect()

    try:
        offset = (page - 1) * limit

        pg_datasets, total_pg = await storage.postgres.list_datasets(offset, limit)

        redis_ids = await storage.redis.keys("*")
        redis_datasets = []

        for dataset_id in redis_ids:
            if any(d["id"] == dataset_id for d in pg_datasets):
                continue

            try:
                data = await storage.redis.get(dataset_id)
                if data:
                    redis_datasets.append(
                        {
                            "id": data["id"],
                            "schema": data["schema_name"],
                            "seed": data.get("seed"),
                            "count": len(data.get("data", {}).get("items", [])),
                            "chaos_applied": data.get("chaos_applied", []),
                            "created_at": data["created_at"],
                            "expires_at": data["expires_at"],
                        }
                    )
            except Exception as e:
                logger.warning(
                    "redis_dataset_retrieval_failed", id=dataset_id, error=str(e)
                )
                continue

        formatted_datasets = [
            {
                "id": d["id"],
                "schema": d["schema_name"],
                "seed": d["seed"],
                "count": d["count"],
                "chaos_applied": d["chaos_applied"] or [],
                "created_at": d["created_at"].isoformat(),
                "expires_at": d["expires_at"].isoformat(),
            }
            for d in pg_datasets
        ]

        if page == 1:
            formatted_datasets = redis_datasets + formatted_datasets
            formatted_datasets = formatted_datasets[:limit]

        total = total_pg + len(redis_ids)
        has_next = offset + limit < total
        has_prev = page > 1

        logger.info(
            "datasets_listed",
            page=page,
            limit=limit,
            returned=len(formatted_datasets),
            total=total,
            from_postgres=len(pg_datasets),
            from_redis=len(redis_datasets),
        )

        return JSONResponse(
            {
                "datasets": formatted_datasets,
                "pagination": {
                    "page": page,
                    "limit": limit,
                    "total": total,
                    "has_next": has_next,
                    "has_prev": has_prev,
                },
            }
        )

    finally:
        await storage.close()


@router.get("/data/{id}")
async def retrieve_dataset_metadata(id: str) -> JSONResponse:
    """Retrieve dataset metadata (lightweight, no items).

    Checks Redis (hot cache) first, then PostgreSQL (warm storage).
    Returns 404 if not found or expired.

    For full items, use GET /data/{id}/items

    Args:
        id: Dataset ID

    Returns:
        Dataset metadata without items
    """
    storage = StorageManager()
    await storage.connect()

    try:
        metadata = await storage.retrieve_metadata(id)

        if not metadata:
            raise HTTPException(
                status_code=404,
                detail=f"Dataset '{id}' not found or expired (30-day retention)",
            )

        response = {
            "id": metadata.id,
            "schema": metadata.schema_name,
            "seed": metadata.seed,
            "count": metadata.count,
            "chaos_applied": metadata.chaos_applied or [],
            "created_at": metadata.created_at.isoformat(),
            "expires_at": metadata.expires_at.isoformat(),
        }

        logger.info("metadata_retrieved", id=id, schema=metadata.schema_name)

        return JSONResponse(response)

    finally:
        await storage.close()


@router.get("/data/{id}/items")
async def retrieve_dataset_items(id: str) -> JSONResponse:
    """Retrieve full dataset with all items (explicit, heavyweight).

    Use this when you need the actual data items.
    For just metadata, use GET /data/{id}

    Args:
        id: Dataset ID

    Returns:
        Full dataset with all items and metadata
    """
    storage = StorageManager()
    await storage.connect()

    try:
        dataset = await storage.retrieve(id)

        if not dataset:
            raise HTTPException(
                status_code=404,
                detail=f"Dataset '{id}' not found or expired (30-day retention)",
            )

        response = {
            "id": dataset.id,
            "schema": dataset.schema_name,
            "items": dataset.data.get("items", []),
            "metadata": {
                "seed": dataset.seed,
                "chaos_applied": dataset.chaos_applied or [],
                "created_at": dataset.created_at.isoformat(),
                "expires_at": dataset.expires_at.isoformat(),
            },
        }

        if dataset.metadata:
            response["metadata"].update(dataset.metadata)

        logger.info(
            "dataset_items_retrieved",
            id=id,
            schema=dataset.schema_name,
            count=len(response["items"]),
        )

        return JSONResponse(response)

    finally:
        await storage.close()


@router.delete("/data/{id}")
async def delete_dataset(id: str) -> JSONResponse:
    """Delete a persisted dataset.

    Removes from both Redis and PostgreSQL.

    Args:
        id: Dataset ID

    Returns:
        Success confirmation
    """
    storage = StorageManager()
    await storage.connect()

    try:
        deleted = await storage.delete(id)

        if not deleted:
            raise HTTPException(status_code=404, detail=f"Dataset '{id}' not found")

        logger.info("dataset_deleted", id=id)

        return JSONResponse({"deleted": True, "id": id})

    finally:
        await storage.close()
