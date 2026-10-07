"""Map reliability is tested without relying on external tile servers."""

import struct
import time
import zlib
import os
from types import SimpleNamespace

import pytest
import requests
from kivy.base import EventLoop
from kivy.core.window import Window

from todaygo.maps import MapPanel, MoscowMap, ObservedSource
from todaygo.tile_transport import USER_AGENT, load_tile, validate_png


def png_tile():
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    pixels = (b"\x00" + b"\x11\x21\x31\xff" * 256) * 256
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 256, 256, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


class Response:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield self.data


def test_https_cache_replaces_corrupt_tile_without_redownloading(monkeypatch, tmp_path):
    target = tmp_path / "tile.png"
    target.write_bytes(b"<html>cached proxy error</html>")
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response(png_tile())

    monkeypatch.setattr(requests, "get", get)
    assert load_tile("https://tiles.example/12/1/2.png", target) == str(target)
    assert load_tile("https://tiles.example/12/1/2.png", target) == str(target)
    assert len(calls) == 1
    assert calls[0][1]["verify"] is True
    assert calls[0][1]["timeout"] == (3, 7)
    assert calls[0][1]["headers"]["User-Agent"] == USER_AGENT
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("payload", [b"<html>Access denied</html>", png_tile()[:-20]])
def test_failed_image_never_enters_cache(monkeypatch, tmp_path, payload):
    monkeypatch.setattr(requests, "get", lambda *_, **__: Response(payload))
    target = tmp_path / "tile.png"
    with pytest.raises(ValueError):
        load_tile("https://tiles.example/12/1/2.png", target)
    assert not target.exists()
    with pytest.raises(ValueError):
        load_tile("http://tiles.example/12/1/2.png", target)


def test_damaged_png_crc_is_rejected():
    damaged = bytearray(png_tile())
    damaged[-8] ^= 1
    with pytest.raises(ValueError):
        validate_png(bytes(damaged))


def test_stale_valid_tile_remains_available_when_network_is_down(monkeypatch, tmp_path):
    target = tmp_path / "cached.png"
    target.write_bytes(png_tile())
    os.utime(target, (0, 0))

    def unavailable(*_, **__):
        raise requests.ConnectTimeout("Simulated outage")

    monkeypatch.setattr(requests, "get", unavailable)
    assert load_tile("https://tiles.example/12/1/2.png", target) == str(target)
    validate_png(target.read_bytes())


def test_tile_success_cancels_already_queued_provider_failure(monkeypatch):
    monkeypatch.setenv("TODAYGO_MAP_MODE", "offline")
    monkeypatch.setattr(ObservedSource, "fill_tile", lambda *args: None)
    EventLoop.ensure_window()
    city = MoscowMap()
    try:
        city._start_provider(0)
        original = city.map_source
        for _ in range(3):
            city.tile_finished(original, False)
        city.tile_finished(original, True)
        EventLoop.idle()
        assert city.map_source is original and not city.offline
    finally:
        city.dispose()


def test_disposed_map_cannot_queue_tiles_or_restart_after_delayed_focus(monkeypatch):
    monkeypatch.setenv("TODAYGO_MAP_MODE", "offline")
    downloaded = []
    monkeypatch.setattr("todaygo.maps.load_tile", lambda *args: downloaded.append(args))
    EventLoop.ensure_window()
    panel = MapPanel()
    panel.map._forced_offline = False
    panel.map.retry_online()
    source = panel.map.map_source
    panel.map.dispose()
    panel.focus(55.7, 37.6)
    stopped = SimpleNamespace(state="loading")
    source.fill_tile(stopped)
    deadline = time.monotonic() + 0.4
    while time.monotonic() < deadline:
        EventLoop.idle()
        time.sleep(0.01)
    assert stopped.state == "done"
    assert not downloaded and not panel.map._tiles


def wait_for(predicate, seconds=4):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        EventLoop.idle()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Map did not reach the expected state")


def test_map_failover_offline_and_retry_render_real_tiles(monkeypatch, tmp_path):
    monkeypatch.delenv("TODAYGO_MAP_MODE", raising=False)
    phase = ["offline"]
    downloaded = []
    real_image = tmp_path / "valid.png"
    real_image.write_bytes(png_tile())

    def download(url, filename, *_):
        downloaded.append(url)
        if phase[0] == "offline" or (phase[0] == "hot" and "tile.openstreetmap.org" in url):
            raise requests.ConnectTimeout("Simulated unavailable provider")
        return str(real_image)

    monkeypatch.setattr("todaygo.maps.load_tile", download)
    EventLoop.ensure_window()
    panel = MapPanel(size_hint=(None, None), size=(430, 380))
    EventLoop.window.add_widget(panel)
    selected = []
    event = {"id": 7, "latitude": 55.7638, "longitude": 37.5927, "category": "music"}
    panel.map.display_events([event], selected.append)
    try:
        wait_for(lambda: panel.map.map_status.startswith("Карта недоступна"))
        assert panel.map.offline and panel.map._schematic in panel.map._layers
        assert "не для навигации" in panel.attribution_label.text
        assert any("openstreetmap.org" in url for url in downloaded)
        assert any("a.tile.openstreetmap.fr/hot" in url for url in downloaded)
        phase[0] = "hot"
        panel.retry_button.dispatch("on_release")
        wait_for(lambda: not panel.map.offline)
        assert isinstance(panel.map.map_source, ObservedSource)
        assert panel.map.map_source.provider_name == "OSM France / HOT"
        assert panel.map._schematic not in panel.map._layers
        assert panel.attribution_label.text == "© OpenStreetMap contributors · HOT · OSM France"
        assert any(tile.texture is not None for tile in panel.map._tiles)
        panel.map.event_markers[0].dispatch("on_release")
        assert selected == [7]
        assert panel.map.event_markers[0].color[3] == 0
        previous = panel.map.map_source
        phase[0] = "osm"
        panel.retry_button.dispatch("on_release")
        panel.map.tile_finished(previous, True)
        assert panel.map.offline  # An obsolete provider cannot mark the new attempt ready.
        wait_for(lambda: not panel.map.offline)
        assert panel.map.map_source.provider_name == "OpenStreetMap"
        assert panel.attribution_label.text == "© OpenStreetMap contributors"
        panel.focus(55.7638, 37.5927, zoom=13)
        wait_for(lambda: abs(panel.map.lat - 55.7638) < 0.0001)
        assert len(panel.map.event_markers) == 1
    finally:
        panel.map.dispose()
        EventLoop.window.remove_widget(panel)


def test_home_map_keeps_its_center_after_detail_navigation_and_window_resize(monkeypatch):
    from todaygo.application import TodayGoApp

    monkeypatch.setenv("TODAYGO_MAP_MODE", "offline")
    event = {
        "id": 101,
        "title": "Встреча в Москве",
        "description": "Гуляем вместе.",
        "latitude": 55.7064,
        "longitude": 37.6407,
        "category": "music",
        "address": "Москва",
        "starts_at": "2099-10-01T12:00:00Z",
        "author_name": "Организатор",
        "attendees": 0,
        "capacity": 30,
        "joined": False,
        "can_edit": False,
    }
    events = [event, {**event, "id": 102, "latitude": 55.7528, "longitude": 37.6331}]
    previous_window = tuple(Window.size)
    app = TodayGoApp()
    app.root = app.build()
    monkeypatch.setattr(app.api, "events", lambda **_: {"items": events, "total": 2})
    monkeypatch.setattr(app.api, "event", lambda _: event)
    EventLoop.window.add_widget(app.root)

    def settle():
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline or app.busy or app.manager.transition.is_active:
            EventLoop.idle()
            time.sleep(0.01)
            assert time.monotonic() < deadline + 3

    try:
        settle()
        home = app.screens["home"].map_panel.map
        assert len(home.event_markers) == 2
        app.go_detail(event["id"])
        settle()
        detail = next(w.map for w in app.screens["detail"].walk() if isinstance(w, MapPanel))
        assert detail is not home and detail.zoom == 14
        Window.size = (360, 700)
        app.go_home()
        settle()
        assert abs(home.lat - 55.751244) < 0.0001
        assert abs(home.lon - 37.618423) < 0.0001
        assert home.zoom == 12 and len(home.event_markers) == 2
        assert abs(detail.lat - event["latitude"]) < 0.0001
        Window.size = (480, 960)
        settle()
        assert abs(home.lat - 55.751244) < 0.0001 and home.zoom == 12
    finally:
        app.on_stop()
        EventLoop.window.remove_widget(app.root)
        Window.size = previous_window
