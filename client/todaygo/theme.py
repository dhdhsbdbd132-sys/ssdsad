"""Midnight Moscow: shared controls, typography and original vector artwork."""

import math
from pathlib import Path

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.core.text import Label as CoreLabel
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.graphics import Canvas, Color, Ellipse, Line, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.properties import BooleanProperty, ListProperty, NumericProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.spinner import Spinner, SpinnerOption
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

from todaygo.motion import enter, reduced_motion

LabelBase.register("Today", str(Path(__file__).resolve().parents[1] / "assets/DejaVuSans.ttf"))
BG = (0.035, 0.052, 0.09, 1)
SURFACE = (0.072, 0.097, 0.155, 1)
SURFACE_HIGH = (0.10, 0.134, 0.20, 1)
STROKE = (0.19, 0.24, 0.33, 1)
WHITE = (1, 1, 1, 1)
INK = (0.94, 0.96, 0.98, 1)
MUTED = (0.57, 0.64, 0.73, 1)
LIME = (0.79, 0.96, 0.39, 1)
BLUE = LIME  # Compatibility with existing primary-action and focus styling.
CYAN = (0.40, 0.80, 0.96, 1)
CORAL = (1, 0.50, 0.40, 1)
VIOLET = (0.68, 0.57, 1, 1)
PALE = SURFACE_HIGH
RED = (1, 0.43, 0.46, 1)
GREEN = LIME
CATEGORIES = {
    "all": "Все",
    "culture": "Культура",
    "music": "Музыка",
    "sport": "Спорт",
    "community": "Встречи",
    "education": "Обучение",
}
CATEGORY_COLORS = {
    "culture": VIOLET,
    "music": CORAL,
    "sport": LIME,
    "community": CYAN,
    "education": (1, 0.77, 0.36, 1),
}
ROLES = {
    "attendee": "Участник",
    "organizer": "Организатор",
    "moderator": "Модератор",
    "admin": "Администратор",
}


def _shade(color, amount):
    return tuple(min(1, max(0, channel * amount)) for channel in color[:3]) + (color[3],)


class Panel(BoxLayout):
    fill = ListProperty(SURFACE)

    def __init__(self, radius=20, **kwargs):
        self.radius = radius
        super().__init__(**kwargs)
        with self.canvas.before:
            self.shadow_color = Color(0, 0, 0, 0.16 if radius else 0)
            self.shadow = RoundedRectangle(radius=[dp(radius)])
            self.color_instruction = Color(*self.fill)
            self.rect = RoundedRectangle(radius=[dp(radius)])
            self.border_color = Color(*STROKE[:3], 0.48 if radius else 0)
            self.outline = Line(rounded_rectangle=(0, 0, 1, 1, dp(radius)), width=1)
        self.bind(pos=self.redraw, size=self.redraw, fill=self.redraw)
        self.redraw()

    def redraw(self, *_):
        self.shadow.pos = (self.x, self.y - dp(3))
        self.shadow.size = self.size
        self.rect.pos, self.rect.size = self.pos, self.size
        self.color_instruction.rgba = self.fill
        self.outline.rounded_rectangle = (*self.pos, *self.size, dp(self.radius))


class Action(Button):
    fill = ListProperty(LIME)
    tint_rgba = ListProperty(LIME)
    hover = BooleanProperty(False)
    press = NumericProperty(0)

    def __init__(self, text, callback=None, secondary=False, danger=False, **kwargs):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(48))
        kwargs.setdefault("font_size", sp(13))
        kwargs.setdefault("font_name", "Today")
        kwargs.setdefault("bold", True)
        kwargs.setdefault("color", RED if danger else INK if secondary else BG)
        kwargs.setdefault("disabled_color", MUTED)
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_color", (0, 0, 0, 0))
        kwargs.setdefault("halign", "center")
        kwargs.setdefault("valign", "middle")
        super().__init__(text=text, **kwargs)
        self.secondary = secondary
        self.danger = danger
        self.fill = (0.22, 0.105, 0.15, 1) if danger else SURFACE_HIGH if secondary else LIME
        self.tint_rgba = self.fill
        self._hover_bound = False
        with self.canvas.before:
            self.shadow_color = Color(0, 0, 0, 0.14)
            self.shadow = RoundedRectangle(radius=[dp(14)])
            self.tint = Color(*self.tint_rgba)
            self.rect = RoundedRectangle(radius=[dp(14)])
            self.border_color = Color(*STROKE[:3], 0.65 if secondary else 0)
            self.outline = Line(rounded_rectangle=(0, 0, 1, 1, dp(14)), width=1)
        self.bind(pos=self.redraw, size=self.redraw, tint_rgba=self.redraw, press=self.redraw)
        self.bind(state=self._state, fill=self._tint, hover=self._tint, parent=self._parent)
        self.bind(size=self._text_size)
        if callback:
            self.bind(on_release=lambda *_: callback())
        self.redraw()
        self._text_size()

    def _text_size(self, *_):
        self.text_size = (max(1, self.width - dp(12)), self.height)

    def _parent(self, _, parent):
        if parent is not None and not self._hover_bound:
            Window.bind(mouse_pos=self._mouse)
            self._hover_bound = True
        elif parent is None:
            if self._hover_bound:
                Window.unbind(mouse_pos=self._mouse)
                self._hover_bound = False
            Animation.cancel_all(self, "tint_rgba", "press")
            self.press = 0
            self.hover = False

    def _mouse(self, _, pos):
        # to_widget transforms window coordinates correctly inside ScrollViews.
        self.hover = bool(self.get_root_window()) and self.collide_point(*self.to_widget(*pos))

    def _state(self, *_):
        self._tint()
        Animation.cancel_all(self, "press")
        value = 1 if self.state == "down" else 0
        if reduced_motion():
            self.press = value
        else:
            Animation(press=value, duration=0.12, t="out_quad").start(self)

    def _tint(self, *_):
        if not hasattr(self, "rect"):
            return
        Animation.cancel_all(self, "tint_rgba")
        target = _shade(self.fill, 0.84 if self.state == "down" else 1.12 if self.hover else 1)
        if reduced_motion():
            self.tint_rgba = target
        else:
            Animation(tint_rgba=target, duration=0.16, t="out_quad").start(self)

    def redraw(self, *_):
        if not hasattr(self, "rect"):
            return
        offset = dp(self.press)
        self.shadow.pos = (self.x, self.y - dp(2))
        self.shadow.size = self.size
        self.rect.pos = (self.x, self.y - offset)
        self.rect.size = self.size
        self.tint.rgba = self.tint_rgba
        self.outline.rounded_rectangle = (self.x, self.y - offset, *self.size, dp(14))


class NavAction(Action):
    active = BooleanProperty(False)

    def __init__(self, text, callback=None, active=False, **kwargs):
        self._label = text
        kwargs.setdefault("font_size", sp(11))
        kwargs.setdefault("height", dp(57))
        icon, _, label = text.partition(" ")
        super().__init__(icon + "\n" + label if label else text, callback, secondary=True, **kwargs)
        with self.canvas.after:
            self.indicator_color = Color(*LIME[:3], 0)
            self.indicator = RoundedRectangle(radius=[dp(2)])
        # Reference-list size callbacks can run before center_x has been invalidated.
        # Finish placement after the current layout pass, with one coalesced callback.
        self._indicator_event = Clock.create_trigger(self._indicator, 0)
        self.bind(active=self._active, pos=self._indicator_event, size=self._indicator_event)
        self.active = active
        self._active()

    def _active(self, *_):
        self.fill = SURFACE_HIGH if self.active else SURFACE
        self.color = LIME if self.active else MUTED
        self.border_color.a = 0
        self.indicator_color.a = 1 if self.active else 0
        self._indicator_event()

    def _parent(self, widget, parent):
        super()._parent(widget, parent)
        if parent is None and hasattr(self, "_indicator_event"):
            self._indicator_event.cancel()

    def _indicator(self, *_):
        self.indicator.pos = (self.x + self.width / 2 - dp(9), self.y + dp(4))
        self.indicator.size = (dp(18), dp(2))


class Field(TextInput):
    ring = NumericProperty(0)

    def __init__(self, hint="", **kwargs):
        kwargs.setdefault("multiline", False)
        kwargs.setdefault("height", dp(50))
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("font_size", sp(14))
        kwargs.setdefault("font_name", "Today")
        kwargs.setdefault("foreground_color", INK)
        kwargs.setdefault("hint_text_color", MUTED)
        kwargs.setdefault("cursor_color", LIME)
        kwargs.setdefault("selection_color", (*LIME[:3], 0.24))
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_active", "")
        kwargs.setdefault("background_color", (0, 0, 0, 0))
        kwargs.setdefault("padding", (dp(15), dp(14)))
        super().__init__(hint_text=hint, **kwargs)
        # Insert behind TextInput's native cursor and foreground instructions.
        # Appending a Color would tint its glyphs and paint over its cursor.
        self.field_canvas = Canvas()
        with self.field_canvas:
            self.field_tint = Color(*BG)
            self.field_rect = RoundedRectangle(radius=[dp(14)])
            self.ring_tint = Color(*STROKE)
            self.field_border = Line(rounded_rectangle=(0, 0, 1, 1, dp(14)), width=1)
        self.canvas.before.insert(0, self.field_canvas)
        self.bind(pos=self.redraw, size=self.redraw, ring=self.redraw)
        self.bind(focus=self._focus, parent=self._parent)
        self.redraw()

    def _focus(self, *_):
        Animation.cancel_all(self, "ring")
        value = 1 if self.focus else 0
        if reduced_motion():
            self.ring = value
        else:
            Animation(ring=value, duration=0.18, t="out_quad").start(self)

    def _parent(self, _, parent):
        if parent is None:
            Animation.cancel_all(self, "ring")

    def redraw(self, *_):
        self.field_rect.pos, self.field_rect.size = self.pos, self.size
        self.field_border.rounded_rectangle = (*self.pos, *self.size, dp(14))
        self.ring_tint.rgba = tuple(
            start + (end - start) * self.ring for start, end in zip(STROKE, LIME, strict=True)
        )
        self.field_border.width = 1 + self.ring * 0.5


class _SelectOption(SpinnerOption):
    def __init__(self, **kwargs):
        kwargs.setdefault("font_name", "Today")
        kwargs.setdefault("font_size", sp(13))
        kwargs.setdefault("height", dp(46))
        kwargs.setdefault("color", INK)
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_color", SURFACE_HIGH)
        super().__init__(**kwargs)


class Select(Spinner):
    """Themed, keyboard/touch accessible choice control using standard Spinner APIs."""

    def __init__(self, **kwargs):
        kwargs.setdefault("font_name", "Today")
        kwargs.setdefault("font_size", sp(13))
        kwargs.setdefault("height", dp(48))
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("color", INK)
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_color", (0, 0, 0, 0))
        kwargs.setdefault("option_cls", _SelectOption)
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(*SURFACE_HIGH)
            self.rect = RoundedRectangle(radius=[dp(14)])
            Color(*STROKE)
            self.outline = Line(rounded_rectangle=(0, 0, 1, 1, dp(14)), width=1)
        self.bind(pos=self.redraw, size=self.redraw)
        self.redraw()

    def redraw(self, *_):
        self.rect.pos, self.rect.size = self.pos, self.size
        self.outline.rounded_rectangle = (*self.pos, *self.size, dp(14))


class Copy(Label):
    def __init__(self, text="", size=14, color=INK, bold=False, height=30, **kwargs):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("halign", "left")
        kwargs.setdefault("valign", "middle")
        super().__init__(
            text=text,
            font_name="Today",
            font_size=sp(size),
            color=color,
            bold=bold,
            height=dp(height),
            **kwargs,
        )
        self.bind(size=self.sync_text)
        self.sync_text()

    def sync_text(self, *_):
        self.text_size = self.size


class Paragraph(Copy):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(width=self.measure, texture_size=self.measure)

    def sync_text(self, *_):
        self.text_size = (self.width, None)

    def measure(self, *_):
        self.text_size = (self.width, None)
        if abs(self.height - self.texture_size[1] - dp(14)) > 0.1:
            self.height = self.texture_size[1] + dp(14)


class Avatar(FloatLayout):
    def __init__(self, initials="СИ", size=48, color=LIME, **kwargs):
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("width", dp(size))
        kwargs.setdefault("height", dp(size))
        super().__init__(**kwargs)
        self.accent = color
        with self.canvas.before:
            Color(*color[:3], 0.13)
            self.disc = Ellipse()
            Color(*color[:3], 0.55)
            self.rim = Line(circle=(0, 0, 1), width=1)
        self.label = Copy(
            text=initials[:2].upper(),
            size=max(12, size * 0.32),
            bold=True,
            color=color,
            halign="center",
            size_hint=(1, 1),
            pos_hint={"x": 0, "y": 0},
        )
        self.add_widget(self.label)
        self.bind(pos=self.redraw, size=self.redraw)
        self.redraw()

    def redraw(self, *_):
        self.disc.pos, self.disc.size = self.pos, self.size
        self.rim.circle = (self.center_x, self.center_y, min(self.size) / 2 - dp(1))


class Badge(Panel):
    def __init__(self, text, category="community", color=None, **kwargs):
        accent = color or CATEGORY_COLORS.get(category, LIME)
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("height", dp(27))
        kwargs.setdefault("padding", (dp(10), 0))
        kwargs.setdefault("fill", tuple(channel * 0.16 for channel in accent[:3]) + (1,))
        super().__init__(radius=9, **kwargs)
        self.shadow_color.a = 0
        self.border_color.a = 0
        self.label = Copy(text=text, size=10, color=accent, bold=True, height=27)
        self.label.bind(text=self._measure, font_size=self._measure)
        self.add_widget(self.label)
        self._measure()

    def _measure(self, *_):
        # Measure separately so resizing the chip cannot cause a texture/layout loop.
        measured = CoreLabel(
            text=self.label.text, font_name="Today", font_size=self.label.font_size, bold=True
        )
        measured.refresh()
        self.width = measured.texture.size[0] + dp(20)


class Artwork(Widget):
    """An original Moscow-inspired skyline, event orbit and glowing route dots."""

    progress = NumericProperty(1)
    orbit = NumericProperty(1)

    def __init__(self, category="community", **kwargs):
        super().__init__(**kwargs)
        self.accent = CATEGORY_COLORS.get(category, LIME)
        self.bind(pos=self.redraw, size=self.redraw, progress=self.redraw, orbit=self.redraw)
        self.bind(parent=self._parent)
        self.redraw()

    def _parent(self, _, parent):
        Animation.cancel_all(self, "progress", "orbit")
        if parent is None or reduced_motion():
            self.progress = self.orbit = 1
            return
        self.progress = 0.2
        self.orbit = 0
        Animation(progress=1, duration=0.9, t="out_cubic").start(self)
        Animation(orbit=1, duration=2.2, t="out_cubic").start(self)

    def redraw(self, *_):
        self.canvas.clear()
        w, h = self.width, self.height
        if min(w, h) <= 0:
            return
        unit = min(w, h)
        cx, cy = self.x + w * 0.53, self.y + h * 0.48
        r = unit * 0.43
        with self.canvas:
            Color(*self.accent[:3], 0.035)
            Ellipse(pos=(cx - r, cy - r), size=(2 * r, 2 * r))
            Color(*self.accent[:3], 0.13)
            Line(ellipse=(cx - r, cy - r * 0.64, 2 * r, r * 1.28), width=1)
            Line(circle=(cx, cy, r * 0.7), width=1)
            # Fine urban grid gives the silhouette a map-like setting.
            Color(*CYAN[:3], 0.10)
            for fraction in (-0.5, 0, 0.5):
                px = cx + fraction * r
                Line(points=(px, cy - r * 0.7, px, cy + r * 0.7), width=0.7)
            base = cy - r * 0.44
            buildings = (
                (-0.65, 0.20, 0.55),
                (-0.39, 0.18, 0.91),
                (-0.15, 0.24, 1.17),
                (0.15, 0.20, 0.76),
                (0.42, 0.16, 0.45),
            )
            for index, (offset, width, height) in enumerate(buildings):
                rise = min(1, max(0.05, (self.progress - index * 0.09) / 0.64))
                x, bw, bh = cx + offset * r, width * r, height * r * rise
                Color(*(self.accent[:3] if index == 2 else CYAN[:3]), 0.28 if index == 2 else 0.13)
                RoundedRectangle(pos=(x, base), size=(bw, bh), radius=[dp(3)])
                Color(*(self.accent[:3] if index == 2 else CYAN[:3]), 0.75 if index == 2 else 0.4)
                Line(points=(x, base, x, base + bh, x + bw, base + bh, x + bw, base), width=1)
                if index == 2:
                    topx = x + bw / 2
                    Line(points=(topx, base + bh, topx, base + bh + r * 0.22), width=1.5)
                Color(*INK[:3], 0.26)
                for floor in (0.25, 0.5, 0.75):
                    Line(
                        points=(x + bw * 0.2, base + bh * floor, x + bw * 0.8, base + bh * floor),
                        width=0.8,
                    )
            Color(*self.accent[:3], 0.7)
            Line(points=(cx - r * 0.85, base, cx + r * 0.8, base), width=1.2)
            angle = (0.65 + self.orbit * 1.6) * math.pi
            dx, dy = cx + math.cos(angle) * r, cy + math.sin(angle) * r * 0.64
            Color(*self.accent[:3], 0.12)
            Ellipse(pos=(dx - dp(10), dy - dp(10)), size=(dp(20), dp(20)))
            Color(*self.accent)
            Ellipse(pos=(dx - dp(3), dy - dp(3)), size=(dp(6), dp(6)))
            Color(*CORAL)
            Ellipse(pos=(cx - r * 0.7 - dp(3), cy + r * 0.38), size=(dp(6), dp(6)))
            Color(*LIME)
            Line(points=(cx + r * 0.71, cy + r * 0.69, cx + r * 0.82, cy + r * 0.69), width=1.2)
            Line(points=(cx + r * 0.765, cy + r * 0.635, cx + r * 0.765, cy + r * 0.745), width=1.2)


class Hero(Panel):
    def __init__(
        self,
        text,
        subtitle="",
        eyebrow="МОСКВА • СЕГОДНЯ ИДЁМ",
        category="community",
        height=190,
        compact=False,
        **kwargs,
    ):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(height))
        kwargs.setdefault("fill", SURFACE)
        super().__init__(radius=24, **kwargs)
        self.content = FloatLayout()
        self.add_widget(self.content)
        self.art = Artwork(
            category=category, size_hint=(0.37, 0.95), pos_hint={"right": 1, "y": 0.02}
        )
        self.content.add_widget(self.art)
        self.eyebrow = Copy(
            text=eyebrow, size=8 if compact else 9, bold=True, color=LIME, height=18
        )
        self._hero_text = text
        self._fit_key = None
        self.heading = Copy(text=text, size=23 if compact else 27, bold=True, valign="middle")
        self.subtitle = Copy(text=subtitle, size=10 if compact else 11, color=MUTED)
        self.content.add_widget(self.eyebrow)
        self.content.add_widget(self.heading)
        self.content.add_widget(self.subtitle)
        self.compact = compact
        self.bind(pos=self._layout, size=self._layout, parent=self._parent)
        self._layout()

    def _parent(self, _, parent):
        if parent is not None:
            enter(self, delay=0.04)

    def _fit_heading(self, width, height):
        key = (round(width, 1), round(height, 1), self._hero_text, self.compact)
        if key == self._fit_key:
            return
        self._fit_key = key
        minimum = 16 if self.compact else 18
        font = 23 if self.compact else 27

        def fits(text, size):
            measured = CoreLabel(
                text=text,
                font_name="Today",
                font_size=sp(size),
                bold=True,
                text_size=(max(1, width), None),
            )
            measured.refresh()
            return measured.texture.size[1] <= height + 0.5

        while font > minimum and not fits(self._hero_text, font):
            font -= 1
        display = self._hero_text
        if not fits(display, font):
            # Very long event titles keep their complete text in the detail body.
            # Find the longest readable prefix here instead of drawing beyond the hero.
            lower, upper = 0, len(display)
            while lower < upper:
                middle = (lower + upper + 1) // 2
                candidate = display[:middle].rstrip() + "…"
                if fits(candidate, font):
                    lower = middle
                else:
                    upper = middle - 1
            display = display[:lower].rstrip(" ,.;") + "…"
        self.heading.font_size = sp(font)
        self.heading.text = display

    def _layout(self, *_):
        compact_short = self.compact and self.height < dp(130)
        inset = dp(14 if compact_short else 18 if self.compact else 22)
        left_width = max(dp(120), self.width * 0.67 - inset)
        text_x = self.x + inset
        eyebrow_height = dp(12 if compact_short else 14 if self.compact else 16)
        gap = dp(4 if compact_short else 6 if self.compact else 8)
        available = max(dp(30), self.height - inset * 2)
        subtitle_height = (
            min(dp(18 if compact_short else 25 if self.compact else 42), available * 0.29)
            if self.subtitle.text
            else 0
        )
        eyebrow_y = self.top - inset - eyebrow_height
        subtitle_y = self.y + inset
        title_y = subtitle_y + subtitle_height + (gap if subtitle_height else 0)
        title_height = max(dp(18), eyebrow_y - gap - title_y)
        for label, y, height in (
            (self.eyebrow, eyebrow_y, eyebrow_height),
            (self.heading, title_y, title_height),
            (self.subtitle, subtitle_y, subtitle_height),
        ):
            label.size_hint = (None, None)
            label.pos = (text_x, y)
            label.size = (left_width, height)
        self._fit_heading(left_width, title_height)
