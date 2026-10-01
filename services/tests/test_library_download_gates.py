"""download_gates: SoC temperature, free space, Mopidy stream-proxy probe."""
from __future__ import annotations

from aiohttp import web
from boombox_library.download_gates import MopidyStreamProbe, free_bytes, read_soc_temp_c


def test_soc_temp_reads_millidegrees_and_absent_means_none(tmp_path):
    assert read_soc_temp_c(tmp_path / "nope") is None
    (tmp_path / "junk").write_text("hot\n")
    assert read_soc_temp_c(tmp_path / "junk") is None
    (tmp_path / "temp").write_text("70000\n")
    assert read_soc_temp_c(tmp_path / "temp") == 70.0


def test_free_bytes(tmp_path):
    assert (free_bytes(tmp_path) or 0) > 0
    assert free_bytes(tmp_path / "missing") is None


class FakeMopidy:
    def __init__(self) -> None:
        self.state = "playing"
        self.uri: str | None = "http://127.0.0.1:6687/api/library/stream/t1"

    def app(self) -> web.Application:
        async def rpc(req: web.Request) -> web.Response:
            method = (await req.json())["method"]
            result: object = None
            if method == "core.playback.get_state":
                result = self.state
            elif method == "core.playback.get_current_track":
                result = {"uri": self.uri} if self.uri else None
            return web.json_response({"jsonrpc": "2.0", "id": 1, "result": result})
        app = web.Application()
        app.router.add_post("/mopidy/rpc", rpc)
        return app


async def test_probe_detects_stream_proxy_playback(aiohttp_server):
    fake = FakeMopidy()
    srv = await aiohttp_server(fake.app())
    probe = MopidyStreamProbe(str(srv.make_url("/mopidy/rpc")))
    try:
        assert await probe.is_streaming() is True
        fake.uri = "file:///opt/boombox/storage/music/audio/t1.flac"
        assert await probe.is_streaming() is False
        fake.uri = "http://127.0.0.1:6687/api/library/stream/t1"
        fake.state = "paused"
        assert await probe.is_streaming() is False
    finally:
        await probe.close()


async def test_probe_with_mopidy_down_is_not_streaming():
    probe = MopidyStreamProbe("http://127.0.0.1:1/mopidy/rpc")
    try:
        assert await probe.is_streaming() is False
    finally:
        await probe.close()
