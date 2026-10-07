from pathlib import Path
from kivy.core.text import LabelBase
from kivy.metrics import dp, sp
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.textinput import TextInput
from kivy.graphics import Color, RoundedRectangle
from kivy.properties import ListProperty

LabelBase.register("Today", str(Path(__file__).resolve().parents[1] / "assets/DejaVuSans.ttf"))
BG = (0.955, 0.967, 0.982, 1)
WHITE = (1, 1, 1, 1)
INK = (0.09, 0.14, 0.24, 1)
MUTED = (0.43, 0.48, 0.57, 1)
BLUE = (0.15, 0.35, 0.94, 1)
PALE = (0.91, 0.94, 1, 1)
RED = (0.85, 0.2, 0.25, 1)
GREEN = (0.14, 0.55, 0.42, 1)
CATEGORIES = {
    "all": "Все",
    "culture": "Культура",
    "music": "Музыка",
    "sport": "Спорт",
    "community": "Встречи",
    "education": "Обучение",
}
CATEGORY_COLORS = {
    "culture": (0.52, 0.32, 0.84, 1),
    "music": (0.93, 0.39, 0.31, 1),
    "sport": GREEN,
    "community": BLUE,
    "education": (0.85, 0.6, 0.15, 1),
}
ROLES = {
    "attendee": "Участник",
    "organizer": "Организатор",
    "moderator": "Модератор",
    "admin": "Администратор",
}


class Panel(BoxLayout):
    fill = ListProperty(WHITE)

    def __init__(self, radius=20, **kwargs):
        super().__init__(**kwargs)
        self.radius = radius
        with self.canvas.before:
            self.color_instruction = Color(*self.fill)
            self.rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(radius)])
        self.bind(pos=self.redraw, size=self.redraw, fill=self.redraw)

    def redraw(self, *_):
        self.rect.pos, self.rect.size = self.pos, self.size
        self.color_instruction.rgba = self.fill


class Action(Button):
    def __init__(self, text, callback=None, secondary=False, danger=False, **kwargs):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(48))
        kwargs.setdefault("font_size", sp(13))
        super().__init__(
            text=text,
            font_name="Today",
            bold=True,
            color=RED if danger else BLUE if secondary else WHITE,
            background_normal="",
            background_down="",
            background_color=(0, 0, 0, 0),
            **kwargs,
        )
        self.fill = (1, 0.94, 0.94, 1) if danger else PALE if secondary else BLUE
        with self.canvas.before:
            self.tint = Color(*self.fill)
            self.rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(13)])
        self.bind(pos=self.redraw, size=self.redraw, state=self.redraw)
        if callback:
            self.bind(on_release=lambda *_: callback())

    def redraw(self, *_):
        self.rect.pos, self.rect.size = self.pos, self.size
        self.tint.rgba = (
            tuple(x * 0.87 for x in self.fill[:3]) + (1,) if self.state == "down" else self.fill
        )


class Field(TextInput):
    def __init__(self, hint="", **kwargs):
        kwargs.setdefault("multiline", False)
        kwargs.setdefault("height", dp(48))
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("font_size", sp(14))
        super().__init__(
            hint_text=hint,
            font_name="Today",
            foreground_color=INK,
            hint_text_color=MUTED,
            cursor_color=BLUE,
            background_normal="",
            background_active="",
            background_color=(0.96, 0.97, 0.99, 1),
            padding=(dp(13), dp(13)),
            **kwargs,
        )


class Copy(Label):
    def __init__(self, text="", size=14, color=INK, bold=False, height=30, **kwargs):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("halign", "left")
        super().__init__(
            text=text,
            font_name="Today",
            font_size=sp(size),
            color=color,
            bold=bold,
            height=dp(height),
            valign="middle",
            **kwargs,
        )
        self.bind(size=self.sync_text)

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
