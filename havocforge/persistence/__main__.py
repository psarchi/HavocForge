from __future__ import annotations

import sys


def main():
    """Dispatch to batch_sync or metrics_collector based on command."""
    if len(sys.argv) < 2:
        print("Usage: python -m havocforge.persistence [batch_sync|metrics_collector]")
        sys.exit(1)

    command = sys.argv[1]

    if command == "batch_sync":
        from havocforge.persistence.batch_sync import main as batch_sync_main
        import asyncio

        asyncio.run(batch_sync_main())
    elif command == "metrics_collector":
        from havocforge.persistence.metrics_collector import (
            main as metrics_collector_main,
        )
        import asyncio

        asyncio.run(metrics_collector_main())
    else:
        print(f"Unknown command: {command}")
        print("Available commands: batch_sync, metrics_collector")
        sys.exit(1)


if __name__ == "__main__":
    main()
