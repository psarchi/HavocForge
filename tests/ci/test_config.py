from __future__ import annotations



def test_default_configs_load():
    """Ensure config manager loads default configs without unexpected keys errors."""
    from havocforge.config import get_config_manager

    cm = get_config_manager()
    server = cm.get_root("server")
    generation = cm.get_root("generation")
    chaos = cm.get_root("chaos")

    assert server is not None
    assert generation is not None
    assert chaos is not None
