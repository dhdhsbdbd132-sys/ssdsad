"""Approximate bundled city diagram: always explicitly labelled as a schematic."""

import json
from pathlib import Path
from kivy.graphics import Color, Line, RoundedRectangle, Rectangle, Ellipse
from kivy_garden.mapview import MapLayer, MapSource
from kivy.metrics import dp
from todaygo.theme import Copy, BG, MUTED, CYAN


class OfflineSource(MapSource):
    def __init__(self):
        super().__init__(
            url="offline://moscow", min_zoom=10, max_zoom=19, attribution="Авторская схема Москвы"
        )

    def fill_tile(self, tile):
        tile.state = "done"


class MoscowSchematic(MapLayer):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.data = json.loads(
            (Path(__file__).resolve().parents[1] / "assets/moscow-schematic.json").read_text(
                encoding="utf-8"
            )
        )

    def reposition(self):
        m = self.parent
        if not m:
            return
        self.canvas.clear()
        self.clear_widgets()

        def xy(p):
            return m.get_window_xy_from(p[0], p[1], m.zoom)

        def points(path):
            return [v for p in path for v in xy(p)]

        with self.canvas:
            Color(*BG)
            Rectangle(pos=m.pos, size=m.size)
            for park in self.data["parks"]:
                south, west, north, east = park["bounds"]
                x, y = xy((south, west))
                xx, yy = xy((north, east))
                Color(0.09, 0.20, 0.18, 1)
                RoundedRectangle(pos=(x, y), size=(xx - x, yy - y), radius=[dp(12)])
                Color(0.21, 0.37, 0.29, 0.6)
                Line(rounded_rectangle=(x, y, xx - x, yy - y, dp(12)), width=dp(0.8))
            for road in self.data["roads"]:
                Color(0.13, 0.18, 0.25, 1)
                width = dp(4 if road["kind"] == "ring" else 3 if road["kind"] == "main" else 2)
                Line(points=points(road["points"]), width=width)
                Color(0.27, 0.33, 0.42, 1)
                Line(points=points(road["points"]), width=max(1, width - dp(1.2)))
            Color(0.05, 0.21, 0.31, 1)
            Line(points=points(self.data["river"]), width=dp(9), joint="round", cap="round")
            Color(*CYAN[:3], 0.45)
            Line(points=points(self.data["river"]), width=dp(1.4), joint="round", cap="round")
        labels = self.data["labels"] + [[p["name"], *p["label"]] for p in self.data["parks"]]
        for title, lat, lon in labels:
            x, y = xy((lat, lon))
            if m.x + dp(40) < x < m.right - dp(40) and m.y + dp(20) < y < m.top - dp(25):
                label = Copy(
                    text=title,
                    size=8 if m.zoom < 13 else 10,
                    color=MUTED,
                    bold=True,
                    size_hint=(None, None),
                    width=dp(135),
                    height=dp(20),
                    halign="center",
                    pos=(x - dp(67), y - dp(10)),
                )
                self.add_widget(label)
        x, y = xy((55.750, 37.616))
        with self.canvas:
            Color(*CYAN[:3], 0.15)
            Ellipse(pos=(x - dp(12), y - dp(12)), size=(dp(24), dp(24)))
            Color(*CYAN)
            Ellipse(pos=(x - dp(3), y - dp(3)), size=(dp(6), dp(6)))
