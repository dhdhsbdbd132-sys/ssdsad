"""Short, cancellable UI motion; no timers or perpetual animation loops."""

import os

from kivy.animation import Animation
from kivy.clock import Clock


def reduced_motion():
    return os.environ.get("TODAYGO_REDUCED_MOTION", "").lower() in {"1", "true", "yes"}


def enter(widget, delay=0, offset=0):
    """Fade a widget into its final layout without animating layout-owned coordinates."""
    del offset  # Layouts own their children's positions; entrance never fights the layout.
    Animation.cancel_all(widget, "opacity")
    if reduced_motion():
        widget.opacity = 1
        return
    pending = getattr(widget, "_todaygo_enter_event", None)
    if pending is not None:
        pending.cancel()
    widget.opacity = 0

    def reveal(_):
        widget._todaygo_enter_event = None
        if widget.parent is not None:
            Animation(opacity=1, duration=0.32, t="out_cubic").start(widget)
        else:
            widget.opacity = 1

    widget._todaygo_enter_event = Clock.schedule_once(reveal, max(0, delay))
    if not getattr(widget, "_todaygo_motion_bound", False):
        widget.bind(parent=_detach)
        widget._todaygo_motion_bound = True


def _detach(widget, parent):
    if parent is not None:
        return
    pending = getattr(widget, "_todaygo_enter_event", None)
    if pending is not None:
        pending.cancel()
        widget._todaygo_enter_event = None
    Animation.cancel_all(widget, "opacity")
    widget.opacity = 1
