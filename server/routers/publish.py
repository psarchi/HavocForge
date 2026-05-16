from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from havocforge.config import get_config_manager
from havocforge.context import GenContext
from server.auth import RequireAuth
from server.deps import get_generator
from server.logging import get_logger
from server.publishers import KafkaPublisher, PubSubPublisher

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/publish", tags=["publish"])


class PublishRequest(BaseModel):
    """Request body for publishing data."""

    count: int = Field(
        1, ge=1, le=100000, description="Number of events to generate and publish"
    )
    topic: str | None = Field(
        None, description="Topic name (overrides default schema topic)"
    )
    batch_size: int = Field(
        1000, ge=1, le=10000, description="Batch size for publishing"
    )


class PublishResponse(BaseModel):
    """Response for publish operations."""

    success: bool
    schema: str  # type: ignore[assignment]
    topic: str
    provider: str
    generated: int
    sent: int
    failed: int
    batches: int
    elapsed_seconds: float


def init_publishers_from_config(app) -> None:
    """Eagerly construct Kafka/PubSub publisher objects on app startup.

    Called from the FastAPI lifespan. Construction is sync (the underlying
    Kafka producer / PubSub client are connected lazily on first publish),
    but constructing the publisher objects here ensures that two concurrent
    first-requests cannot race to instantiate them.
    """
    cm = get_config_manager()

    app.state.kafka_publisher = None
    app.state.pubsub_publisher = None

    if cm.get_value("server.publishing.kafka.enabled", False):
        bootstrap_servers = cm.get_value(
            "server.publishing.kafka.bootstrap_servers", "localhost:9092"
        )
        app.state.kafka_publisher = KafkaPublisher(bootstrap_servers=bootstrap_servers)
        logger.info("kafka_publisher_constructed", bootstrap_servers=bootstrap_servers)

    if cm.get_value("server.publishing.pubsub.enabled", False):
        project_id = cm.get_value("server.publishing.pubsub.project_id", "")
        if project_id:
            app.state.pubsub_publisher = PubSubPublisher(project_id=project_id)
            logger.info("pubsub_publisher_constructed", project_id=project_id)
        else:
            logger.warning("pubsub_publisher_skipped_no_project_id")


def get_kafka_publisher(request: Request) -> KafkaPublisher:
    """FastAPI dependency: return the lifespan-initialized Kafka publisher."""
    publisher = getattr(request.app.state, "kafka_publisher", None)
    if publisher is None:
        raise HTTPException(
            status_code=503,
            detail="Kafka publishing is not enabled (set server.publishing.kafka.enabled=true and restart).",
        )
    return publisher


def get_pubsub_publisher(request: Request) -> PubSubPublisher:
    """FastAPI dependency: return the lifespan-initialized Pub/Sub publisher."""
    publisher = getattr(request.app.state, "pubsub_publisher", None)
    if publisher is None:
        raise HTTPException(
            status_code=503,
            detail="Pub/Sub publishing is not enabled (set server.publishing.pubsub.enabled=true and project_id, then restart).",
        )
    return publisher


async def generate_and_publish(
    schema: str,
    count: int,
    batch_size: int,
    publisher,
    topic: str,
) -> PublishResponse:
    """Generate data and publish in batches.

    Args:
        schema: Schema name to generate
        count: Total number of events to generate
        batch_size: Batch size for publishing
        publisher: Publisher instance (Kafka or Pub/Sub)
        topic: Topic name to publish to

    Returns:
        PublishResponse with results
    """
    import time

    start_time = time.time()

    # Get generator
    try:
        gen = get_generator(schema)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Schema not found: {schema}")

    total_sent = 0
    total_failed = 0
    batch_count = 0
    ctx = GenContext(seed=None)
    ctx.schema_name = schema

    for batch_start in range(0, count, batch_size):
        batch_end = min(batch_start + batch_size, count)
        batch_count_items = batch_end - batch_start

        items = [gen.generate(ctx) for _ in range(batch_count_items)]

        try:
            result = await publisher.publish(topic, items)
            total_sent += result.get("sent", 0)
            total_failed += result.get("failed", 0)
            batch_count += 1

            logger.debug(
                "publish_batch_complete",
                schema=schema,
                topic=topic,
                batch=batch_count,
                sent=result.get("sent", 0),
            )
        except Exception as e:
            logger.error(
                "publish_batch_failed", schema=schema, topic=topic, error=str(e)
            )
            total_failed += batch_count_items

        await asyncio.sleep(0)

    elapsed = time.time() - start_time

    logger.info(
        "publish_complete",
        schema=schema,
        topic=topic,
        generated=count,
        sent=total_sent,
        failed=total_failed,
        batches=batch_count,
        elapsed=elapsed,
    )

    return PublishResponse(
        success=True,
        schema=schema,
        topic=topic,
        provider=publisher.__class__.__name__.replace("Publisher", "").lower(),
        generated=count,
        sent=total_sent,
        failed=total_failed,
        batches=batch_count,
        elapsed_seconds=round(elapsed, 3),
    )


@router.post("/kafka/{schema}", response_model=PublishResponse)
async def publish_to_kafka(
    schema: str,
    request: PublishRequest,
    publisher: KafkaPublisher = Depends(get_kafka_publisher),
    _token: RequireAuth = None,
) -> PublishResponse:
    """Generate and publish data to a Kafka topic.

    Requires authentication via token. Returns 503 if Kafka publishing was
    not enabled at startup (lifespan-time configuration).
    """
    topic = request.topic or schema

    return await generate_and_publish(
        schema=schema,
        count=request.count,
        batch_size=request.batch_size,
        publisher=publisher,
        topic=topic,
    )


@router.post("/pubsub/{schema}", response_model=PublishResponse)
async def publish_to_pubsub(
    schema: str,
    request: PublishRequest,
    publisher: PubSubPublisher = Depends(get_pubsub_publisher),
    _token: RequireAuth = None,
) -> PublishResponse:
    """Generate and publish data to a Google Cloud Pub/Sub topic.

    Requires authentication via token. Returns 503 if Pub/Sub publishing was
    not enabled at startup (lifespan-time configuration).
    """
    topic = request.topic or schema

    return await generate_and_publish(
        schema=schema,
        count=request.count,
        batch_size=request.batch_size,
        publisher=publisher,
        topic=topic,
    )


@router.get("/health")
async def health_check(http_request: Request, _token: RequireAuth = None) -> dict[str, Any]:
    """Report health for whichever publishers were initialized at startup."""
    health: dict[str, Any] = {}

    kafka = getattr(http_request.app.state, "kafka_publisher", None)
    if kafka is not None:
        try:
            health["kafka"] = kafka.health_check()
        except Exception as e:
            logger.error("kafka_health_check_failed", error=str(e))
            health["kafka"] = {"error": str(e)}

    pubsub = getattr(http_request.app.state, "pubsub_publisher", None)
    if pubsub is not None:
        try:
            health["pubsub"] = pubsub.health_check()
        except Exception as e:
            logger.error("pubsub_health_check_failed", error=str(e))
            health["pubsub"] = {"error": str(e)}

    return {"publishers": health}


async def shutdown_publishers(app) -> None:
    """Close lifespan-owned publishers on app shutdown."""
    kafka = getattr(app.state, "kafka_publisher", None)
    if kafka is not None:
        try:
            await kafka.close()
        finally:
            app.state.kafka_publisher = None

    pubsub = getattr(app.state, "pubsub_publisher", None)
    if pubsub is not None:
        try:
            await pubsub.close()
        finally:
            app.state.pubsub_publisher = None

    logger.info("publishers_shutdown_complete")
