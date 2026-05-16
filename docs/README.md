# Documentation

Havocforge API is a FastAPI service for generating realistic synthetic data from YAML schemas. You define the shape and constraints of your data, hit an endpoint, get records back. It also does real-time WebSocket streaming, dual-layer persistence, and has a built-in chaos injection system for testing how well your consumers handle bad data.

This is the full docs index. Pick where you need to start.

| Doc | What's in it |
|-----|-------------|
| [Quickstart](quickstart.md) | Get running in 5 minutes |
| [Schema Guide](schema-guide.md) | All generator types, entity correlation, JSON→YAML tool |
| [API Reference](api.md) | HTTP endpoints and WebSocket streaming |
| [Chaos Engineering](chaos.md) | Every chaos op, how it works, and how to configure it |
| [Configuration](configuration.md) | All three config files explained |
| [Performance](performance.md) | Full single-instance benchmark matrix — 30 cells, worker scaling, feature cost, schema complexity, pre-gen worker fill rate |
