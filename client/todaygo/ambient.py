"""A single, touch-transparent Moscow night sky shared by all app screens.

The soft light is a small reusable texture. Only existing canvas instructions
move at 24 fps; there are no shaders, per-screen loops or external assets.
"""

import math

from kivy.clock import Clock
from kivy.graphics import Color, Ellipse, Line, Rectangle
from kivy.graphics.texture import Texture
from kivy.metrics import dp
from kivy.properties import BooleanProperty
from kivy.uix.widget import Widget

from todaygo.motion import reduced_motion
from todaygo.theme import BG, CYAN, LIME, VIOLET


_GLOW_TEXTURE = None
_GLOW_PIXELS = None


def _restore_glow(texture):
    texture.blit_buffer(_GLOW_PIXELS, colorfmt="rgba", bufferfmt="ubyte")


def _glow_texture():
    """A feathered glow, kept in memory for Android graphics-context recovery."""
    global _GLOW_TEXTURE, _GLOW_PIXELS
    if _GLOW_TEXTURE is None:
        side = 96
        pixels = bytearray()
        for row in range(side):
            y = 2 * row / (side - 1) - 1
            for column in range(side):
                x = 2 * column / (side - 1) - 1
                radius = x * x + y * y
                alpha = math.exp(-2.0 * radius) * max(0, 1 - radius) ** 2
                pixels.extend((255, 255, 255, round(255 * alpha)))
        _GLOW_PIXELS = bytes(pixels)
        _GLOW_TEXTURE = Texture.create(size=(side, side), colorfmt="rgba")
        _GLOW_TEXTURE.min_filter = _GLOW_TEXTURE.mag_filter = "linear"
        _restore_glow(_GLOW_TEXTURE)
        _GLOW_TEXTURE.add_reload_observer(_restore_glow)
    return _GLOW_TEXTURE


class AmbientBackdrop(Widget):
    """Aurora fields, moving orbital lights and a quiet Moscow silhouette.

    Put this widget beneath the ScreenManager. Call ``set_active(False)`` when
    the application pauses, ``set_active(True)`` on resume and ``dispose()`` on
    stop. Detaching also stops the one clock event. Reduced motion preserves
    the complete composition without scheduling any animation.
    """

    active = BooleanProperty(True)
    frame_interval = 1 / 24

    def __init__(self, **kwargs):
        self._event = None
        self._disposed = False
        self._elapsed = 0.0
        self._geometry_key = None
        super().__init__(**kwargs)
        texture = _glow_texture()
        with self.canvas:
            Color(*BG)
            self._base = Rectangle()
            self._fields = []
            # x, y, width, height, colour, alpha, phase: intentionally asymmetrical.
            for spec in (
                (0.08, 0.94, 1.75, 0.88, CYAN, 0.40, 0.0),
                (0.95, 0.76, 1.62, 0.96, VIOLET, 0.38, 2.1),
                (0.58, 1.07, 1.90, 0.48, LIME, 0.23, 4.3),
                (0.04, 0.16, 1.22, 0.70, VIOLET, 0.27, 3.2),
                (1.03, 0.05, 1.48, 0.83, CYAN, 0.25, 1.4),
            ):
                tint = Color(*spec[4][:3], spec[5])
                glow = Rectangle(texture=texture)
                self._fields.append((spec, tint, glow))

            self._orbits = []
            for phase, vertical, flatten in ((0.6, 0.77, 0.30), (2.8, 0.27, 0.38)):
                tint = Color(*CYAN[:3], 0.13)
                line = Line(width=dp(0.8))
                trail_tint = Color(*LIME[:3], 0.32)
                trail = Line(width=dp(1.1))
                glow_tint = Color(*LIME[:3], 0.55)
                glow = Rectangle(texture=texture)
                Color(*LIME[:3], 0.83)
                point = Ellipse()
                self._orbits.append(
                    (
                        phase,
                        vertical,
                        flatten,
                        tint,
                        line,
                        trail_tint,
                        trail,
                        glow_tint,
                        glow,
                        point,
                    )
                )

            self._stars = []
            # A deterministic constellation stays still when resizing or restarting.
            for index in range(22):
                x = (index * 0.61803398875 + 0.11) % 1
                y = (index * 0.41421356237 + 0.17) % 1
                accent = CYAN if index % 3 else LIME
                tint = Color(*accent[:3], 0.3)
                dot = Ellipse()
                self._stars.append((index, x, y, tint, dot))

            Color(*CYAN[:3], 0.08)
            self._city_fill = Rectangle()
            Color(*CYAN[:3], 0.16)
            self._skyline = Line(width=dp(0.8))
            Color(*LIME[:3], 0.13)
            self._horizon = Line(width=dp(0.8))

        self.bind(pos=self._redraw, size=self._redraw, parent=self._sync, active=self._sync)
        self._redraw()

    @property
    def animating(self):
        return self._event is not None

    def set_active(self, active):
        self.active = bool(active)
        # Also re-check the environment if an accessibility setting changed.
        self._sync()

    def _sync(self, *_):
        should_run = (
            self.parent is not None and self.active and not self._disposed and not reduced_motion()
        )
        if not should_run:
            self._cancel()
            if reduced_motion():
                self._elapsed = 0
                self._redraw()
        elif self._event is None:
            self._event = Clock.schedule_interval(self._tick, self.frame_interval)

    def _cancel(self):
        if self._event is not None:
            self._event.cancel()
            self._event = None

    def dispose(self):
        """Permanently release the animation; safe to call repeatedly."""
        self._disposed = True
        self._cancel()

    def _tick(self, dt):
        # A callback already in the clock queue must not restart after detach.
        if self.parent is None or not self.active or self._disposed or reduced_motion():
            self._sync()
            return False
        # Returning from pause never causes a large visual jump.
        self._elapsed += min(max(dt, 0), 0.1)
        self._redraw()

    def _redraw(self, *_):
        if not hasattr(self, "_base"):
            return
        self._base.pos, self._base.size = self.pos, self.size
        if min(self.size) <= 0:
            return
        w, h, now = self.width, self.height, self._elapsed
        key = (self.x, self.y, w, h)
        geometry_changed = key != self._geometry_key
        for spec, tint, glow in self._fields:
            fx, fy, fw, fh, _, alpha, phase = spec
            drift = now * 0.14 + phase
            cx = self.x + w * (fx + math.sin(drift) * 0.085)
            cy = self.y + h * (fy + math.cos(drift * 0.73) * 0.038)
            pulse = 1 + math.sin(drift * 0.8) * 0.10
            gw, gh = w * fw * pulse, h * fh * pulse
            glow.pos, glow.size = (cx - gw / 2, cy - gh / 2), (gw, gh)
            tint.a = alpha * (0.92 + 0.08 * math.sin(drift))

        for phase, vertical, flatten, _, line, trail_tint, trail, _, glow, point in self._orbits:
            cx, cy = self.x + w * 0.53, self.y + h * vertical
            rx, ry = w * 0.70, w * flatten
            tilt = -0.20

            def orbital(angle):
                ox, oy = math.cos(angle) * rx, math.sin(angle) * ry
                return (
                    cx + ox * math.cos(tilt) - oy * math.sin(tilt),
                    cy + ox * math.sin(tilt) + oy * math.cos(tilt),
                )

            # Full arcs are fixed geometry; rebuilding only happens on size/pos change.
            if geometry_changed:
                line.points = tuple(
                    coordinate for i in range(65) for coordinate in orbital(i * math.tau / 64)
                )
            angle = phase + now * 0.10
            trail.points = tuple(
                coordinate for i in range(10) for coordinate in orbital(angle - (9 - i) * 0.024)
            )
            trail_tint.a = 0.23 + 0.09 * math.sin(now * 0.4 + phase)
            px, py = orbital(angle)
            glow_radius, point_radius = dp(13), dp(1.8)
            glow.pos = (px - glow_radius, py - glow_radius)
            glow.size = (glow_radius * 2, glow_radius * 2)
            point.pos = (px - point_radius, py - point_radius)
            point.size = (point_radius * 2, point_radius * 2)

        for index, fx, fy, tint, dot in self._stars:
            # Drift is deliberately measured in a few pixels, not screen fractions.
            px = self.x + fx * w + math.sin(now * 0.13 + index) * dp(2.5)
            py = self.y + fy * h + math.cos(now * 0.12 + index) * dp(3)
            radius = dp(1.0 if index % 4 else 1.5)
            dot.pos, dot.size = (px - radius, py - radius), (2 * radius, 2 * radius)
            tint.a = 0.14 + 0.20 * (0.5 + 0.5 * math.sin(now * 0.58 + index * 1.7))

        if not geometry_changed:
            return
        self._geometry_key = key
        # A low, quiet skyline sits behind the footer rather than the page's copy.
        baseline = self.y + h * 0.035
        skyline = [self.x, baseline]
        buildings = (
            (0.04, 0.045, 0.026),
            (0.11, 0.07, 0.041),
            (0.23, 0.046, 0.070),
            (0.29, 0.065, 0.100),
            (0.37, 0.044, 0.054),
            (0.48, 0.06, 0.029),
            (0.60, 0.05, 0.039),
            (0.71, 0.048, 0.074),
            (0.80, 0.063, 0.046),
            (0.91, 0.045, 0.025),
        )
        for fx, fw, fh in buildings:
            x, bw, bh = self.x + fx * w, fw * w, min(h * fh, w * fh * 1.5)
            skyline.extend((x, baseline, x, baseline + bh, x + bw, baseline + bh, x + bw, baseline))
        skyline.extend((self.right, baseline))
        self._skyline.points = skyline
        self._city_fill.pos, self._city_fill.size = self.pos, (w, baseline - self.y)
        self._horizon.points = (self.x, baseline, self.right, baseline)

    def on_touch_down(self, touch):
        return False

    def on_touch_move(self, touch):
        return False

    def on_touch_up(self, touch):
        return False
