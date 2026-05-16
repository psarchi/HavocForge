"""Admin configuration endpoints - rebuilt for current ConfigManager API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from havocforge.config import get_config_manager
from havocforge.config.access import reload_config
from havocforge.config.constants import DEFAULT_CONFIG_DIR
from server.auth import RequireAuth

CONFIG_DIR = DEFAULT_CONFIG_DIR

router = APIRouter(prefix="/v1/admin/config", tags=["admin-config"])


@router.get("/debug")
def get_config_debug(_token: RequireAuth = None) -> dict[str, Any]:
    """Get full config tree for debugging.

    Returns:
        dict with server and generation config sections
    """
    cm = get_config_manager()

    result = {}

    try:
        server_cfg = cm.get_root("server")
        result["server"] = dict(server_cfg) if server_cfg else {}
    except Exception as e:
        result["server"] = {"error": str(e)}

    try:
        gen_cfg = cm.get_root("generation")
        result["generation"] = dict(gen_cfg) if gen_cfg else {}
    except Exception as e:
        result["generation"] = {"error": str(e)}

    return result


@router.get("/server")
def get_server_config(_token: RequireAuth = None) -> dict[str, Any]:
    """Get server configuration section.

    Returns:
        Server config as dict
    """
    cm = get_config_manager()
    server_cfg = cm.get_root("server")
    if not server_cfg:
        raise HTTPException(status_code=404, detail="Server config not found")
    return dict(server_cfg)


@router.get("/generation")
def get_generation_config(_token: RequireAuth = None) -> dict[str, Any]:
    """Get generation configuration section.

    Returns:
        Generation config as dict
    """
    cm = get_config_manager()
    gen_cfg = cm.get_root("generation")
    if not gen_cfg:
        raise HTTPException(status_code=404, detail="Generation config not found")
    return dict(gen_cfg)


@router.post("/server/update")
def update_server_config(
    updates: dict[str, Any] = Body(...),
    _token: RequireAuth = None,
) -> dict[str, Any]:
    """Update server configuration in-memory (non-persistent).

    Args:
        updates: Dictionary of config paths and values to update
                 Example: {"pregeneration.fallback_to_live": false}

    Returns:
        Result of update operation
    """
    try:
        cm = get_config_manager()
        server_cfg = cm.get_root("server")

        if not server_cfg:
            raise HTTPException(status_code=404, detail="Server config not found")

        for path, new_value in updates.items():
            parts = path.split(".")
            current = server_cfg

            for part in parts[:-1]:
                if not hasattr(current, part):
                    raise HTTPException(
                        status_code=404,
                        detail=f"Config path '{path}' not found (missing '{part}')",
                    )
                current = getattr(current, part)

            field_name = parts[-1]
            if not hasattr(current, field_name):
                raise HTTPException(
                    status_code=404,
                    detail=f"Config path '{path}' not found (field '{field_name}' not found)",
                )

            setattr(current, field_name, new_value)

        return {
            "success": True,
            "message": f"Updated {len(updates)} config value(s) in-memory (non-persistent)",
            "updates": updates,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Config update failed: {str(e)}")


@router.post("/generation/update")
def update_generation_config(
    updates: dict[str, Any] = Body(...),
    _token: RequireAuth = None,
) -> dict[str, Any]:
    """Update generation configuration in-memory (non-persistent).

    Args:
        updates: Dictionary of config paths and values to update

    Returns:
        Result of update operation
    """
    try:
        cm = get_config_manager()
        gen_cfg = cm.get_root("generation")

        if not gen_cfg:
            raise HTTPException(status_code=404, detail="Generation config not found")

        for path, new_value in updates.items():
            parts = path.split(".")
            current = gen_cfg

            for part in parts[:-1]:
                if not hasattr(current, part):
                    raise HTTPException(
                        status_code=404,
                        detail=f"Config path '{path}' not found (missing '{part}')",
                    )
                current = getattr(current, part)

            field_name = parts[-1]
            if not hasattr(current, field_name):
                raise HTTPException(
                    status_code=404,
                    detail=f"Config path '{path}' not found (field '{field_name}' not found)",
                )

            setattr(current, field_name, new_value)

        return {
            "success": True,
            "message": f"Updated {len(updates)} config value(s) in-memory (non-persistent)",
            "updates": updates,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Config update failed: {str(e)}")


@router.post("/reload")
def reload_all_config(_token: RequireAuth = None) -> dict[str, Any]:
    """Reload all configuration from disk.

    Returns:
        Reload result
    """
    try:
        reload_config()
        return {
            "success": True,
            "message": "Configuration reloaded from disk",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Config reload failed: {str(e)}")


@router.get("/files")
def list_config_files(_token: RequireAuth = None) -> dict[str, Any]:
    """List available configuration files.

    Returns:
        List of config files and their status
    """
    files = {}

    for yaml_file in CONFIG_DIR.glob("*.yaml"):
        files[yaml_file.name] = {
            "path": str(yaml_file),
            "exists": yaml_file.exists(),
            "size_bytes": yaml_file.stat().st_size if yaml_file.exists() else 0,
        }

    return {"config_dir": str(CONFIG_DIR), "files": files}
