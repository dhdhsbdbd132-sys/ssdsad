"""Real input dispatch catches collisions with Kivy's button events."""

import time

import pytest
from kivy.animation import Animation
from kivy.base import EventLoop
from kivy.tests.common import UnitTestTouch

from todaygo.theme import Action, NavAction


def advance(seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        EventLoop.idle()
        time.sleep(0.01)


@pytest.mark.parametrize("button_cls", [Action, NavAction], ids=["action", "nav"])
@pytest.mark.parametrize("motion", ["animated", "reduced"])
def test_pointer_press_release_preserves_button_events(monkeypatch, button_cls, motion):
    monkeypatch.setenv("TODAYGO_REDUCED_MOTION", "1" if motion == "reduced" else "0")
    EventLoop.ensure_window()
    calls, events = [], []
    button = button_cls(
        "◎ Карта",
        lambda: calls.append("click"),
        size_hint=(None, None),
        pos=(20, 20),
        size=(180, 48),
    )
    button.bind(on_press=lambda *_: events.append("press"))
    button.bind(on_release=lambda *_: events.append("release"))
    EventLoop.window.add_widget(button)
    try:
        advance(0.05)
        touch = UnitTestTouch(*button.center)
        touch.touch_down()
        advance(0.18)
        assert button.state == "down"
        assert events == ["press"] and calls == []
        assert button.press_progress == pytest.approx(1)
        touch.touch_up()
        advance(0.20)
        assert button.state == "normal"
        assert button.press_progress == pytest.approx(0)
        assert events == ["press", "release"]
        assert calls == ["click"]
    finally:
        Animation.cancel_all(button)
        EventLoop.window.remove_widget(button)
