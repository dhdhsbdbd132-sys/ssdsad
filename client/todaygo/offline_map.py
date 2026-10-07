"""Approximate bundled city diagram: always explicitly labelled as a schematic."""

import json
from pathlib import Path
from kivy.graphics import Color, Line, RoundedRectangle, Rectangle
from kivy_garden.mapview import MapLayer, MapSource
from kivy.metrics import dp
from todaygo.theme import Copy


class OfflineSource(MapSource):
    def __init__(self):
        super().__init__(
            url="offline://moscow", min_zoom=10, max_zoom=16, attribution="Авторская схема Москвы"
        )

    def fill_tile(self, tile):
        tile.state = "done"


class MoscowSchematic(MapLayer):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.data = json.loads(
            (Path(__file__).resolve().parents[1] / "assets/moscow-schematic.json").read_text()
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
            Color(0.94, 0.95, 0.955, 1)
            Rectangle(pos=m.pos, size=m.size)
            for park in self.data["parks"]:
                south, west, north, east = park["bounds"]
                x, y = xy((south, west))
                xx, yy = xy((north, east))
                Color(0.84, 0.90, 0.83, 1)
                RoundedRectangle(pos=(x, y), size=(xx - x, yy - y), radius=[dp(12)])
            for road in self.data["roads"]:
                Color(0.83, 0.85, 0.87, 1)
                width = dp(4 if road["kind"] == "ring" else 3 if road["kind"] == "main" else 2)
                Line(points=points(road["points"]), width=width)
                Color(1, 1, 1, 1)
                Line(points=points(road["points"]), width=max(1, width - dp(1.2)))
            Color(0.69, 0.83, 0.93, 1)
            Line(points=points(self.data["river"]), width=dp(9), joint="round", cap="round")
        labels = self.data["labels"] + [[p["name"], *p["label"]] for p in self.data["parks"]]
        for title, lat, lon in labels:
            x, y = xy((lat, lon))
            if m.x + dp(40) < x < m.right - dp(40) and m.y + dp(20) < y < m.top - dp(25):
                label = Copy(
                    text=title,
                    size=8 if m.zoom < 13 else 10,
                    color=(0.43, 0.49, 0.52, 1),
                    bold=True,
                    size_hint=(None, None),
                    width=dp(135),
                    height=dp(20),
                    halign="center",
                    pos=(x - dp(67), y - dp(10)),
                )
                self.add_widget(label)
