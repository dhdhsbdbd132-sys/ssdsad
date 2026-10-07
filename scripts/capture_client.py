"""Render actual Kivy screens against a running API, not UI mockups."""

import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "client"))
os.environ.setdefault("KIVY_HOME", str(root / ".data/kivy"))
from kivy.clock import Clock
from todaygo.application import TodayGoApp

app = TodayGoApp()


def capture(_):
    assert not app.busy and len(app.events) > 0, "API did not supply events"
    app.root.export_to_png(str(root / "docs/moscow-map.png"))
    app.go_auth()
    Clock.schedule_once(capture_auth, 1)


def capture_auth(_):
    app.root.export_to_png(str(root / "docs/login.png"))
    app.go_detail(app.events[0]["id"])
    Clock.schedule_once(capture_detail, 1)


def capture_detail(_):
    assert app.manager.current == "detail", "Event screen did not open"
    app.root.export_to_png(str(root / "docs/event-detail.png"))
    app.stop()


Clock.schedule_once(capture, 4)
app.run()
