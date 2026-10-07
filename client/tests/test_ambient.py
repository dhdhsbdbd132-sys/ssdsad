"""The shared background never steals input or runs after pause/detach."""

import time

from kivy.animation import Animation
from kivy.base import EventLoop
from kivy.tests.common import UnitTestTouch
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.widget import Widget

from todaygo.ambient import AmbientBackdrop
from todaygo.theme import Action


def test_background_has_one_timer_and_stops_across_lifecycle(monkeypatch):
    monkeypatch.setenv("TODAYGO_REDUCED_MOTION", "0")
    host = Widget()
    background = AmbientBackdrop(size=(480, 960))
    assert not background.animating
    host.add_widget(background)
    event = background._event
    assert event is not None and event.is_triggered
    background.set_active(True)
    assert background._event is event
    before = background._fields[0][2].pos
    instruction_count = len(background.canvas.children)
    background._tick(0.1)
    assert background._fields[0][2].pos != before
    assert len(background.canvas.children) == instruction_count

    background.set_active(False)
    assert not background.animating and not event.is_triggered
    elapsed = background._elapsed
    background._tick(30)  # A previously queued frame must not resume it.
    assert background._elapsed == elapsed
    background.set_active(True)
    resumed = background._event
    assert resumed is not None and resumed is not event
    host.remove_widget(background)
    assert not background.animating and not resumed.is_triggered
    background._tick(1)
    assert background._elapsed == elapsed

    host.add_widget(background)
    assert background.animating
    background.dispose()
    background.dispose()
    background.set_active(True)
    assert not background.animating
    host.remove_widget(background)
    host.add_widget(background)
    assert not background.animating
    host.remove_widget(background)


def test_reduced_motion_keeps_static_aurora_without_timer(monkeypatch):
    monkeypatch.setenv("TODAYGO_REDUCED_MOTION", "1")
    host = Widget()
    background = AmbientBackdrop(size=(360, 700))
    host.add_widget(background)
    try:
        assert not background.animating
        initial = background._fields[0][2].pos
        background._tick(10)
        assert background._fields[0][2].pos == initial
        assert background._elapsed == 0
        background.pos = (15, 23)
        background.size = (520, 850)
        assert background._base.pos == (15, 23)
        assert background._base.size == (520, 850)
        assert background._skyline.points[-2:] == [535, 23 + 850 * 0.035]

        monkeypatch.setenv("TODAYGO_REDUCED_MOTION", "0")
        background.set_active(True)
        assert background.animating
        background._tick(0.1)
        monkeypatch.setenv("TODAYGO_REDUCED_MOTION", "1")
        background._tick(0.1)
        assert not background.animating and background._elapsed == 0
    finally:
        background.dispose()
        host.remove_widget(background)


def test_background_passes_real_pointer_input_to_buttons(monkeypatch):
    monkeypatch.setenv("TODAYGO_REDUCED_MOTION", "1")
    EventLoop.ensure_window()
    host = FloatLayout()
    clicks = []
    button = Action(
        "Войти",
        lambda: clicks.append("clicked"),
        pos=(25, 25),
        size=(160, 48),
        size_hint=(None, None),
    )
    host.add_widget(button)
    # Put the background above a button deliberately: even there it passes input.
    background = AmbientBackdrop()
    host.add_widget(background)
    EventLoop.window.add_widget(host)
    try:
        EventLoop.idle()
        touch = UnitTestTouch(*button.center)
        touch.touch_down()
        time.sleep(0.03)
        EventLoop.idle()
        assert button.state == "down"
        touch.touch_up()
        EventLoop.idle()
        assert clicks == ["clicked"]
    finally:
        background.dispose()
        Animation.cancel_all(button)
        EventLoop.window.remove_widget(host)
        host.clear_widgets()
