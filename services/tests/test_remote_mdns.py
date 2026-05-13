"""Tests for mDNS advertisement."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_mdns_service_info_shape(monkeypatch):
    """Verify the ServiceInfo we'd register has the right fields."""
    monkeypatch.setenv("BOOMBOX_ID", "boombox-living-room")
    monkeypatch.setenv("BOOMBOX_NAME", "Living Room")

    # Importing the shim populates sys.modules["boombox_remote_impl"] so the
    # underscore-named inner module is reachable for direct attribute access.
    import boombox_remote  # noqa: F401
    import boombox_remote_impl as br

    info = br.build_mdns_service_info(port=6685)
    assert info.type == "_boombox._tcp.local."
    assert info.name == "boombox-living-room._boombox._tcp.local."
    assert info.port == 6685
    props = {k.decode(): v.decode() for k, v in info.properties.items()}
    assert props["id"] == "boombox-living-room"
    assert props["name"] == "Living Room"
    assert props["version"] == "1"
