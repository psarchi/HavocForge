import asyncio
from havocforge.config import get_config_manager
from havocforge.observability import config_enabled

# TODO: planned couldn't make it work
async def export_config_metrics():
    """Export current config values as Prometheus metrics."""
    cm = get_config_manager()

    configs = {
        "pregeneration_enabled": cm.get_value("pregeneration.enabled", False),
        "chaos_enabled": cm.get_value("chaos.enabled", False),
        "logging_enabled": cm.get_value("server.observability.logging.enabled", True),
        "metadata_enabled": cm.get_value("generation_meta.enabled.status", False),
        "observability_enabled": cm.get_value(
            "server.observability.metrics_enabled", True
        ),
        "per_generator_metrics_enabled": cm.get_value(
            "server.observability.per_generator_metrics", False
        ),
    }

    for key, enabled in configs.items():
        config_enabled.labels(config_key=key).set(1 if enabled else 0)


async def config_exporter_loop():
    """Background task that exports config metrics every 10 seconds."""
    while True:
        try:
            await export_config_metrics()
        except Exception:
            pass  # Silently ignore errors
        await asyncio.sleep(10)
