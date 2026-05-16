"""WebSocket streaming endpoint, decomposed from the original 793-line module.

Sub-modules:

- :mod:`server.routers.streaming.handler` — WebSocket lifecycle + main loop
  (this is where ``router`` is defined).
- :mod:`server.routers.streaming.state` — stateful field metadata, per-user
  state, batch transforms.
- :mod:`server.routers.streaming.chaos_apply` — per-batch chaos application.
- :mod:`server.routers.streaming.live` — live-generation fallback and global
  cache counter maintenance.
- :mod:`server.routers.streaming.profiler` — optional cProfile capture.

External callers should keep importing the package as before — ``router`` is
re-exported here so ``from server.routers import streaming; streaming.router``
continues to work.
"""

from .handler import router

__all__ = ["router"]
