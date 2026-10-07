"""Capture real Kivy screens against a running API, after motion/layout settle."""

import os
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "client"))
os.environ.setdefault("KIVY_HOME", str(root / ".data/kivy"))
from kivy.clock import Clock
from kivy.core.window import Window
from todaygo.application import TodayGoApp

app = TodayGoApp()
steps = []
waiting_since = None


def capture_next(_=0):
    global waiting_since
    if not steps:
        app.stop()
        return
    name, filename, action = steps.pop(0)
    waiting_since = time.monotonic()
    action()
    Clock.schedule_once(lambda _: wait_for_screen(name, filename), 0.1)


def wait_for_screen(name, filename):
    ready = (
        not app.busy
        and app.manager.current == name
        and not app.manager.transition.is_active
        and app.screens[name].layout.opacity >= 0.99
    )
    if name == "home" and os.environ.get("TODAYGO_MAP_MODE") != "offline":
        map_view = app.screens["home"].map_panel.map
        ready = ready and not map_view.map_status.startswith(("Подключаем", "Пробуем"))
    if not ready:
        assert time.monotonic() - waiting_since < 30, f"Screen {name} did not settle"
        Clock.schedule_once(lambda _: wait_for_screen(name, filename), 0.1)
        return
    # Let original skyline motion and tile fades finish; no frame is exported mid-transition.
    Clock.schedule_once(lambda _: export(filename), 2.3)


def export(filename):
    app.root.export_to_png(str(root / "docs" / filename))
    Clock.schedule_once(capture_next, 0.1)


def start(_):
    assert not app.busy and app.events, "API did not supply events"
    steps.extend(
        [
            ("home", "moscow-map.png", lambda: None),
            ("auth", "login.png", app.go_auth),
            ("auth", "registration.png", lambda: app.screens["auth"].build("register")),
            ("profile", "profile.png", app.go_profile),
            ("list", "event-list.png", lambda: app.go_list("all")),
            ("detail", "event-detail.png", lambda: app.go_detail(app.events[0]["id"])),
            ("home", "moscow-small.png", small_home),
        ]
    )
    capture_next()


def small_home():
    Window.size = (360, 700)
    app.go_home()


Clock.schedule_once(start, 4)
app.run()
