"""Optional cProfile capture for a single WebSocket stream.

Extracted from ``streaming.py`` so the WebSocket handler stays focused on
streaming logic. ``StreamProfiler`` is a no-op when profiling isn't requested
or isn't enabled in config — the handler just calls ``.start()`` / ``.stop()``
unconditionally and the helper does the right thing.
"""

from __future__ import annotations

import cProfile
import os
import pstats
import time
from io import StringIO

from server.logging import get_logger

logger = get_logger(__name__)


class StreamProfiler:
    """Encapsulates the request-scoped cProfile lifecycle."""

    def __init__(
        self,
        *,
        requested: bool,
        enabled_in_config: bool,
        output_dir: str | None,
        schema: str,
        user_id: str | None,
    ) -> None:
        self._schema = schema
        self._user_id = user_id
        self._output_dir = output_dir
        self._profile: cProfile.Profile | None = None

        if not requested:
            return
        if not enabled_in_config:
            logger.warning(
                "profiling_requested_but_disabled_by_config", schema=schema
            )
            return
        if not output_dir:
            logger.warning(
                "profiling_requested_but_no_output_dir", schema=schema
            )
            return

        self._profile = cProfile.Profile()

    @property
    def active(self) -> bool:
        return self._profile is not None

    def start(self) -> None:
        if self._profile is not None:
            self._profile.enable()
            logger.info(
                "profiling_enabled",
                schema=self._schema,
                user_id=self._user_id or "auto",
            )

    def stop_and_dump(self, items_sent: int) -> None:
        if self._profile is None or self._output_dir is None:
            return

        self._profile.disable()
        os.makedirs(self._output_dir, exist_ok=True)

        timestamp = int(time.time())
        prefix = f"{self._output_dir}/stream_{self._schema}_{timestamp}"

        profile_file = f"{prefix}.prof"
        report_file = f"{prefix}.txt"
        self._profile.dump_stats(profile_file)

        with open(report_file, "w") as f:
            f.write(f"WebSocket Stream Profile - {self._schema}\n")
            f.write(f"Timestamp: {timestamp}\n")
            f.write(f"User ID: {self._user_id}\n")
            f.write(f"Items sent: {items_sent}\n")
            f.write("=" * 80 + "\n\n")

            for sort_key, header in (
                ("cumulative", "CUMULATIVE TIME (including subcalls)"),
                ("time", "TIME (excluding subcalls)"),
            ):
                f.write(header + "\n")
                f.write("=" * 80 + "\n")
                buf = StringIO()
                stats = pstats.Stats(self._profile, stream=buf)
                stats.strip_dirs()
                stats.sort_stats(sort_key)
                stats.print_stats(50)
                f.write(buf.getvalue())
                f.write("\n\n")

        logger.info(
            "profile_saved",
            schema=self._schema,
            timestamp=timestamp,
            user_id=self._user_id,
            items_sent=items_sent,
            profile_file=profile_file,
            report_file=report_file,
        )
