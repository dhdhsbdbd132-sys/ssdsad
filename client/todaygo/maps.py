from kivy_garden.mapview import MapView, MapMarker, MapSource
from kivy.uix.floatlayout import FloatLayout
from kivy.metrics import dp
from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle, Ellipse, Triangle
from kivy.properties import BooleanProperty
from todaygo.offline_map import OfflineSource, MoscowSchematic
from todaygo.theme import Copy, Action, INK, WHITE, CATEGORY_COLORS

MOSCOW = (55.751244, 37.618423)
SOURCE = MapSource(
    url="https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
    min_zoom=1,
    max_zoom=19,
    attribution="© OpenStreetMap contributors © CARTO",
)


class EventPin(MapMarker):
    """Vector marker: category colors are not multiplied by a red bitmap."""

    def __init__(self, category="community", **kwargs):
        self.category_fill = CATEGORY_COLORS[category]
        super().__init__(source="", size=(dp(34), dp(44)), **kwargs)
        self.bind(pos=self.draw_pin, size=self.draw_pin, texture_size=self.fit_pin)
        Clock.schedule_once(self.fit_pin, 0)
        self.draw_pin()

    def fit_pin(self, *_):
        self.size = (dp(34), dp(44))
        if self._layer and self._layer.parent:
            self._layer.set_marker_position(self._layer.parent, self)

    def draw_pin(self, *_):
        self.canvas.after.clear()
        x, y = self.pos
        with self.canvas.after:
            Color(0.06, 0.12, 0.25, 0.14)
            Ellipse(pos=(x + dp(5), y), size=(dp(24), dp(8)))
            Color(*self.category_fill)
            Triangle(points=[x + dp(6), y + dp(20), x + dp(28), y + dp(20), x + dp(17), y + dp(3)])
            Ellipse(pos=(x + dp(1), y + dp(13)), size=(dp(32), dp(32)))
            Color(1, 1, 1, 1)
            Ellipse(pos=(x + dp(10), y + dp(22)), size=(dp(14), dp(14)))


class MoscowMap(MapView):
    picking = BooleanProperty(False)

    def __init__(self, on_pick=None, **kwargs):
        from kivy.app import App
        from pathlib import Path

        app = App.get_running_app()
        cache = Path(app.user_data_dir if app else ".data") / "map-cache"
        cache.mkdir(parents=True, exist_ok=True)
        self._desired_center = MOSCOW
        self.offline = bool(app and getattr(app, "map_offline", False))
        super().__init__(
            lat=MOSCOW[0],
            lon=MOSCOW[1],
            zoom=12,
            map_source=OfflineSource() if self.offline else SOURCE,
            cache_dir=str(cache),
            **kwargs,
        )
        if self.offline:
            self.add_layer(MoscowSchematic())
        self.event_markers = []
        self.on_pick, self._start_touch = on_pick, None

    def center_on(self, *args):
        if len(args) == 2:
            self._desired_center = (args[0], args[1])
        elif len(args) == 1:
            self._desired_center = (args[0].lat, args[0].lon)
        return super().center_on(*args)

    def on_size(self, instance, size):
        if not hasattr(self, "_scatter"):
            return
        for layer in self._layers:
            layer.size = size
        MapView.center_on(self, *self._desired_center)
        self.trigger_update(True)

    def on_pos(self, instance, pos):
        if not hasattr(self, "_scatter"):
            return
        MapView.center_on(self, *self._desired_center)
        self.trigger_update(True)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self._start_touch = touch.pos
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        if self.picking and self._start_touch and self.collide_point(*touch.pos):
            distance = sum((a - b) ** 2 for a, b in zip(touch.pos, self._start_touch)) ** 0.5
            if distance < dp(8) and self.on_pick:
                coords = self.get_latlon_at(touch.x - self.x, touch.y - self.y)
                self.on_pick(coords.lat, coords.lon)
        result = super().on_touch_up(touch)
        Clock.schedule_once(lambda _: setattr(self, "_desired_center", (self.lat, self.lon)), 0.1)
        return result

    def display_events(self, events, callback):
        self.clear_markers()
        for event in events:
            marker = EventPin(
                lat=event["latitude"],
                lon=event["longitude"],
                category=event["category"],
            )
            marker.bind(on_release=lambda _, event_id=event["id"]: callback(event_id))
            self.add_marker(marker)
            self.event_markers.append(marker)

    def clear_markers(self):
        for marker in self.event_markers:
            self.remove_marker(marker)
        self.event_markers = []

    def use_offline(self):
        if self.offline:
            return
        self.offline = True
        self.map_source = OfflineSource()
        self.add_layer(MoscowSchematic())
        self.trigger_update(True)


class MapPanel(FloatLayout):
    def __init__(self, on_pick=None, **kwargs):
        super().__init__(**kwargs)
        self.map = MoscowMap(on_pick=on_pick, pos_hint={"x": 0, "y": 0})
        self.focus_center = MOSCOW
        Clock.schedule_once(lambda _: self.map.center_on(*self.focus_center), 0.35)
        self.add_widget(self.map)
        badge = Copy(
            text="  МОСКВА  •  СОБЫТИЯ РЯДОМ",
            size=10,
            bold=True,
            size_hint=(None, None),
            width=dp(228),
            height=dp(32),
            pos_hint={"x": 0.04, "top": 0.96},
        )
        with badge.canvas.before:
            Color(*WHITE)
            rect = RoundedRectangle(pos=badge.pos, size=badge.size, radius=[dp(12)])
        badge.bind(
            pos=lambda w, _: setattr(rect, "pos", w.pos),
            size=lambda w, _: setattr(rect, "size", w.size),
        )
        self.add_widget(badge)
        for text, top, callback in [
            ("+", 0.78, lambda: setattr(self.map, "zoom", min(19, self.map.zoom + 1))),
            ("−", 0.62, lambda: setattr(self.map, "zoom", max(1, self.map.zoom - 1))),
        ]:
            self.add_widget(
                Action(
                    text,
                    callback,
                    secondary=True,
                    size_hint=(None, None),
                    width=dp(42),
                    height=dp(42),
                    pos_hint={"right": 0.96, "top": top},
                )
            )
        self.add_widget(
            Action(
                "◎",
                lambda: self.map.center_on(*MOSCOW),
                secondary=True,
                size_hint=(None, None),
                width=dp(42),
                height=dp(42),
                pos_hint={"right": 0.96, "y": 0.10},
            )
        )
        label = Copy(
            text="Схема Москвы · офлайн · не для навигации"
            if self.map.offline
            else "© OpenStreetMap contributors  © CARTO",
            size=9,
            color=INK,
            size_hint=(1, None),
            height=dp(22),
            pos_hint={"x": 0.02, "y": 0},
        )
        with label.canvas.before:
            Color(1, 1, 1, 0.9)
            rect2 = RoundedRectangle(pos=label.pos, size=label.size, radius=[0])
        label.bind(
            pos=lambda w, _: setattr(rect2, "pos", w.pos),
            size=lambda w, _: setattr(rect2, "size", w.size),
        )
        self.add_widget(label)
        self.attribution_label = label

    def focus(self, latitude, longitude, zoom=12):
        self.focus_center = (latitude, longitude)
        self.map.zoom = zoom
        self.map.center_on(latitude, longitude)
        Clock.schedule_once(lambda _: self.map.center_on(*self.focus_center), 0.35)
