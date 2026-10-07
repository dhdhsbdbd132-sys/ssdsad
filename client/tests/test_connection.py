"""Phone setup uses a real API and keeps credentials off disk."""

import json
import time

import pytest
from kivy.base import EventLoop

from todaygo.api import ApiClient, ApiError
from todaygo.application import TodayGoApp
import todaygo.application as application
import todaygo.screens as screens


@pytest.mark.parametrize("host", ["192.168.1.24", "10.1.2.3", "172.16.4.5"])
def test_wifi_http_requires_explicit_local_mode(host):
    url = f"http://{host}:8000"
    with pytest.raises(ApiError):
        ApiClient(url)
    assert ApiClient(url, allow_private_http=True).base_url == url


@pytest.mark.parametrize(
    "url",
    [
        "http://8.8.8.8:8000",
        "http://remote.example.com",
        "http://169.254.1.1",
        "http://192.0.2.1",
        "http://172.32.0.1",
        "http://0.0.0.0:8000",
        "http://192.168.1.2:65536",
        "http://192.168.1.2:0",
    ],
)
def test_local_mode_keeps_public_and_invalid_addresses_blocked(url):
    with pytest.raises(ApiError):
        ApiClient(url, allow_private_http=True)


def advance(app, seconds=0.25):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline or app.busy:
        EventLoop.idle()
        time.sleep(0.01)
        if time.monotonic() > deadline + 10:
            raise AssertionError("Phone setup did not settle")


def test_android_first_launch_connects_and_remembers_server(api_server, monkeypatch, tmp_path):
    url, _ = api_server
    monkeypatch.delenv("TODAYGO_API_URL", raising=False)
    monkeypatch.setattr(application, "platform", "android")
    monkeypatch.setattr(screens, "platform", "android")
    monkeypatch.setattr(TodayGoApp, "user_data_dir", property(lambda _: str(tmp_path)))
    app = TodayGoApp()
    app.root = app.build()
    EventLoop.ensure_window()
    EventLoop.window.add_widget(app.root)
    try:
        advance(app)
        assert app.manager.current == "connect" and not app.busy
        setup = app.screens["connect"]
        assert setup.server.text == ""
        assert not setup.lan.active
        setup.server.text = url
        setup.submit()
        advance(app)
        assert app.manager.current == "home" and app.api.base_url == url
        saved = json.loads((tmp_path / "settings.json").read_text())
        assert saved == {"api_url": url, "allow_private_http": False}
        assert "token" not in str(saved)
        assert app.backdrop.animating
        assert app.on_pause()
        assert not app.backdrop.animating
        app.on_resume()
        assert app.backdrop.animating
    finally:
        app.on_stop()
        EventLoop.window.remove_widget(app.root)
    assert not app.backdrop.animating
