from pathlib import Path
from typing import Dict, Any


# placeholders
CONSTRAINT_KEYS = ("ge", "gt", "le", "lt", "in", "regex")
DEFAULT_CHAOS_CONFIG = Path("config/chaos.yaml")
DEFAULT_CONFIG_DIR = Path("config/default")
DEFAULT_GENERATION_CONFIG = Path("config/generation.yaml")
DEFAULT_SERVER_CONFIG = Path("config/server.yaml")
# --


TYPE_MAP: Dict[str, Any] = {
    "string": str,
    "str": str,
    "int": int,
    "integer": int,
    "float": float,
    "number": float,
    "bool": bool,
    "boolean": bool,
    "array": list,
    "list": list,
    "object": dict,
    "dict": dict,
    "group": "group",  # sentinel for containers with children only
}
