"""Moscow maps with observed tile loading, provider recovery, and a bundled diagram."""

import os
import weakref
from pathlib import Path

from kivy.animation import Animation
from kivy.app import App
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.graphics import (
    Color,
    Ellipse,
    Line,
    RoundedRectangle,
    Triangle,
    StencilPush,
    StencilUse,
    StencilUnUse,
    StencilPop,
)
from kivy.metrics import dp
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.uix.floatlayout import FloatLayout
from kivy_garden.mapview import MapMarker, MapSource, MapView
from kivy_garden.mapview.downloader import Downloader

from todaygo.offline_map import MoscowSchematic, OfflineSource
from todaygo.motion import reduced_motion
from todaygo.theme import Action, CATEGORY_COLORS, Copy, INK, MUTED, SURFACE, STROKE
from todaygo.tile_transport import load_tile

MOSCOW = (55.751244, 37.618423)
PROVIDERS = (
    (
        "OpenStreetMap",
        "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "© OpenStreetMap contributors",
    ),
    (
        "OSM France / HOT",
        "https://a.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png",
        "© OpenStreetMap contributors · HOT · OSM France",
    ),
)


class ObservedSource(MapSource):
    """Garden's shared worker pool, with completion reported on the Kivy thread."""

    def __init__(self, owner, provider):
        self.owner = weakref.ref(owner)
        name, url, attribution = provider
        self.provider_name = name
        super().__init__(url=url, min_zoom=10, max_zoom=19, attribution=attribution)

    def fill_tile(self, tile):
        owner = self.owner()
        if not owner or owner._disposed:
            tile.state = "done"
            return
        if tile.state != "done":
            Downloader.instance(cache_dir=tile.cache_dir).submit(self._load, tile)

    def _load(self, tile):
        owner = self.owner()
        if tile.state == "done" or not owner or owner._disposed:
            return None
        row = self.get_row_count(tile.zoom) - tile.tile_y - 1
        url = self.url.format(z=tile.zoom, x=tile.tile_x, y=row)
        try:
            filename = load_tile(url, tile.cache_fn, self.tile_size)
            return self._complete, (tile, filename, None)
        except Exception as exc:
            return self._complete, (tile, None, type(exc).__name__)

    def _complete(self, tile, filename, error):
        owner = self.owner()
        # Removed tiles and results from an old provider must never switch the map back.
        if not owner or owner.map_source is not self or tile.state == "done":
            return
        if filename:
            try:
                image = CoreImage(filename)
                if image.texture is None:
                    raise ValueError("No tile texture")
                tile.set_source(filename)
                owner.animate_tiles()
            except Exception:
                Path(filename).unlink(missing_ok=True)
                filename, error = None, "InvalidImage"
        if not filename:
            tile.state = "done"
        owner.tile_finished(self, bool(filename), error)


class EventPin(MapMarker):
    """Vector pin with a finite entrance pulse and a clear category color."""

    pulse = NumericProperty(0)

    def __init__(self, category="community", **kwargs):
        self.category_fill = CATEGORY_COLORS.get(category, CATEGORY_COLORS["community"])
        # Image's default Rectangle is white when there is no bitmap texture.
        # Hide that canvas; the vector pin below sets its own explicit colors.
        kwargs.setdefault("color", (1, 1, 1, 0))
        super().__init__(source="", size=(dp(36), dp(46)), **kwargs)
        self.bind(
            pos=self.draw_pin, size=self.draw_pin, pulse=self.draw_pin, texture_size=self.fit_pin
        )
        Clock.schedule_once(self.fit_pin, 0)
        if reduced_motion():
            self.pulse = 1
        else:
            Clock.schedule_once(self.animate_pin, 0.12)
        self.draw_pin()

    def animate_pin(self, *_):
        if reduced_motion():
            self.pulse = 1
            return
        Animation(pulse=1, duration=0.65, t="out_quad").start(self)

    def fit_pin(self, *_):
        self.size = (dp(36), dp(46))
        if self._layer and self._layer.parent:
            self._layer.set_marker_position(self._layer.parent, self)

    def draw_pin(self, *_):
        self.canvas.after.clear()
        x, y = self.pos
        with self.canvas.after:
            if self.pulse < 1:
                Color(*self.category_fill[:3], (1 - self.pulse) * 0.36)
                radius = dp(18 + self.pulse * 16)
                Line(circle=(x + dp(18), y + dp(29), radius), width=dp(1.5))
            Color(0, 0, 0, 0.35)
            Ellipse(pos=(x + dp(4), y), size=(dp(28), dp(8)))
            Color(*self.category_fill)
            Triangle(points=[x + dp(6), y + dp(22), x + dp(30), y + dp(22), x + dp(18), y + dp(3)])
            Ellipse(pos=(x + dp(1), y + dp(13)), size=(dp(34), dp(34)))
            Color(*SURFACE)
            Ellipse(pos=(x + dp(11), y + dp(23)), size=(dp(14), dp(14)))
            Color(*self.category_fill)
            Ellipse(pos=(x + dp(16), y + dp(28)), size=(dp(4), dp(4)))


class MoscowMap(MapView):
    picking = BooleanProperty(False)
    offline = BooleanProperty(True)
    map_status = StringProperty("Подключаем карту…")
    attribution = StringProperty("Схема Москвы · не для навигации")

    def __init__(self, on_pick=None, **kwargs):
        app = App.get_running_app()
        cache = Path(app.user_data_dir if app else ".data") / "map-cache"
        cache.mkdir(parents=True, exist_ok=True)
        self._desired_center = MOSCOW
        self._provider_index = 0
        self._failure_streak = 0
        self._deadline = None
        self._startup_event = None
        self._disposed = False
        self._geometry_trigger = Clock.create_trigger(self.recenter_after_layout, 0)
        self._switch_pending = False
        self._forced_offline = os.environ.get("TODAYGO_MAP_MODE") == "offline"
        super().__init__(
            lat=MOSCOW[0],
            lon=MOSCOW[1],
            zoom=12,
            map_source=OfflineSource(),
            cache_dir=str(cache),
            **kwargs,
        )
        self._schematic = MoscowSchematic()
        if reduced_motion():
            self.animation_duration = 0
        self.add_layer(self._schematic)
        self.event_markers = []
        self.on_pick, self._start_touch = on_pick, None
        if self._forced_offline:
            self.map_status = "Схема Москвы · офлайн"
        else:
            self._startup_event = Clock.schedule_once(lambda _: self.retry_online(), 0.2)

    def _cancel_deadline(self):
        if self._deadline:
            self._deadline.cancel()
            self._deadline = None

    def _show_schematic(self):
        if self._schematic not in self._layers:
            # Keep the diagram below existing event markers.
            marker_layers = [layer for layer in self._layers if layer is not self._schematic]
            for layer in marker_layers:
                self.remove_layer(layer)
            self.add_layer(self._schematic)
            for layer in marker_layers:
                self.add_layer(layer)
        self.offline = True

    def _start_provider(self, index):
        self._cancel_deadline()
        self._provider_index, self._failure_streak = index, 0
        self._switch_pending = False
        self._show_schematic()
        self.map_status = "Подключаем карту…" if index == 0 else "Пробуем другой источник…"
        self.attribution = "Схема Москвы · не для навигации"
        self.map_source = ObservedSource(self, PROVIDERS[index])
        source = self.map_source
        self._deadline = Clock.schedule_once(
            lambda _: self._provider_failed(source, timed_out=True), 12
        )
        self.center_on(*self._desired_center)
        self.trigger_update(True)

    def retry_online(self):
        if self._disposed:
            return
        if self._forced_offline:
            self.map_status = "Схема Москвы · офлайн"
            return
        self._start_provider(0)

    def tile_finished(self, source, success, error=None):
        if self._disposed or source is not self.map_source:
            return
        if success:
            self._cancel_deadline()
            self._failure_streak = 0
            self._switch_pending = False
            if self._schematic in self._layers:
                self.remove_layer(self._schematic)
            self.offline = False
            self.map_status = "Карта Москвы · готова"
            self.attribution = source.attribution
        else:
            self._failure_streak += 1
            if self._failure_streak >= 3 and not self._switch_pending:
                self._switch_pending = True
                Clock.schedule_once(lambda _: self._provider_failed(source), 0)

    def _provider_failed(self, expected_source=None, timed_out=False):
        if self._disposed:
            return
        if expected_source is not None and expected_source is not self.map_source:
            return
        if expected_source is not None and not timed_out and self._failure_streak < 3:
            self._switch_pending = False
            return
        if self._provider_index + 1 < len(PROVIDERS):
            self._start_provider(self._provider_index + 1)
        else:
            self.use_offline()

    def use_offline(self):
        self._cancel_deadline()
        self.map_source = OfflineSource()
        self._show_schematic()
        self.map_status = "Карта недоступна · схема Москвы"
        self.attribution = "Схема Москвы · офлайн · не для навигации"
        self.trigger_update(True)

    def center_on(self, *args):
        if self._disposed:
            return
        if len(args) == 2:
            self._desired_center = (args[0], args[1])
        elif len(args) == 1:
            self._desired_center = (args[0].lat, args[0].lon)
        return super().center_on(*args)

    def trigger_update(self, full):
        if not self._disposed:
            return super().trigger_update(full)

    def do_update(self, dt):
        if not self._disposed:
            return super().do_update(dt)

    def animate_tiles(self):
        Clock.unschedule(self._animate_color)
        Clock.schedule_interval(self._animate_color, 1 / 60)

    def _animate_color(self, dt):
        if self._disposed:
            return False
        super()._animate_color(dt)
        # Garden normally runs this callback forever, including on hidden maps.
        # Restart only when a decoded tile actually needs its short fade.
        return any(tile.state == "need-animation" for tile in self._tiles + self._tiles_bg)

    def on_size(self, instance, size):
        if not hasattr(self, "_scatter"):
            return
        for layer in self._layers:
            layer.size = size
        MapView.center_on(self, *self._desired_center)
        self._geometry_trigger()
        self.trigger_update(True)

    def on_pos(self, instance, pos):
        if not hasattr(self, "_scatter"):
            return
        MapView.center_on(self, *self._desired_center)
        self._geometry_trigger()
        self.trigger_update(True)

    def recenter_after_layout(self, *_):
        # Window resizing and ScreenManager can move/resize the scatter after
        # on_size/on_pos fired. Reapply the requested coordinate once layout settles.
        if not self._disposed and hasattr(self, "_scatter"):
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
        self._start_touch = None
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
            Animation.cancel_all(marker)
            self.remove_marker(marker)
        self.event_markers = []

    def dispose(self):
        """Cancel this map's finite pending timeout when its screen is discarded."""
        self._disposed = True
        if self._startup_event:
            self._startup_event.cancel()
            self._startup_event = None
        self._cancel_deadline()
        self._geometry_trigger.cancel()
        for callback in (self.do_update, self._animate_color, self._animate_scale):
            Clock.unschedule(callback)
        self.remove_all_tiles()
        self.clear_markers()


def _floating_surface(widget, radius=12):
    with widget.canvas.before:
        Color(*SURFACE[:3], 0.95)
        rectangle = RoundedRectangle(pos=widget.pos, size=widget.size, radius=[dp(radius)])
        Color(*STROKE)
        border = Line(rounded_rectangle=(*widget.pos, *widget.size, dp(radius)), width=dp(0.7))

    def redraw(*_):
        rectangle.pos, rectangle.size = widget.pos, widget.size
        border.rounded_rectangle = (*widget.pos, *widget.size, dp(radius))

    widget.bind(pos=redraw, size=redraw)


class MapPanel(FloatLayout):
    def __init__(self, on_pick=None, **kwargs):
        super().__init__(**kwargs)
        # Nested stencil instructions preserve MapView's own clipping while rounding
        # the whole map and its floating controls to match the surrounding cards.
        with self.canvas.before:
            StencilPush()
            self.clip_start = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(22)])
            StencilUse()
        with self.canvas.after:
            StencilUnUse()
            self.clip_end = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(22)])
            StencilPop()
            Color(*STROKE)
            self.border = Line(rounded_rectangle=(*self.pos, *self.size, dp(22)), width=dp(0.8))
        self.bind(pos=self.redraw_clip, size=self.redraw_clip)
        self.map = MoscowMap(on_pick=on_pick, pos_hint={"x": 0, "y": 0})
        self.focus_center = MOSCOW
        Clock.schedule_once(lambda _: self.map.center_on(*self.focus_center), 0.35)
        self.add_widget(self.map)
        badge = Copy(
            text="  МОСКВА / НА КАРТЕ",
            size=10,
            bold=True,
            size_hint=(None, None),
            width=dp(178),
            height=dp(32),
            pos_hint={"x": 0.04, "top": 0.96},
        )
        _floating_surface(badge)
        self.add_widget(badge)
        self.status_label = Copy(
            text=self.map.map_status,
            size=9,
            color=MUTED,
            size_hint=(None, None),
            width=dp(224),
            height=dp(25),
            pos_hint={"x": 0.04, "y": 0.19},
        )
        _floating_surface(self.status_label, 9)
        self.add_widget(self.status_label)
        self.zoom_buttons = []
        for text, top, callback in [
            (
                "+",
                0.78,
                lambda: setattr(
                    self.map, "zoom", min(self.map.map_source.max_zoom, self.map.zoom + 1)
                ),
            ),
            (
                "−",
                0.60,
                lambda: setattr(
                    self.map, "zoom", max(self.map.map_source.min_zoom, self.map.zoom - 1)
                ),
            ),
        ]:
            button = Action(
                text,
                callback,
                secondary=True,
                size_hint=(None, None),
                width=dp(42),
                height=dp(42),
                pos_hint={"right": 0.96, "top": top},
            )
            self.zoom_buttons.append(button)
            self.add_widget(button)
        self.focus_button = Action(
            "◎",
            lambda: self.map.center_on(*MOSCOW),
            secondary=True,
            size_hint=(None, None),
            width=dp(42),
            height=dp(42),
            pos_hint={"right": 0.96, "y": 0.08},
        )
        self.add_widget(self.focus_button)
        self.retry_button = Action(
            "Обновить",
            self.map.retry_online,
            secondary=True,
            size_hint=(None, None),
            width=dp(104),
            height=dp(32),
            pos_hint={"x": 0.04, "y": 0.08},
        )
        self.retry_button.disabled = self.map._forced_offline
        self.add_widget(self.retry_button)
        self.attribution_label = Copy(
            text=self.map.attribution,
            size=8,
            color=INK,
            size_hint=(1, None),
            height=dp(25),
            pos_hint={"x": 0, "y": 0},
            halign="center",
        )
        _floating_surface(self.attribution_label, 0)
        self.add_widget(self.attribution_label)
        self.map.bind(
            map_status=lambda _, value: setattr(self.status_label, "text", value),
            attribution=lambda _, value: setattr(self.attribution_label, "text", value),
        )
        self.bind(size=self.position_controls)
        self.position_controls()

    def position_controls(self, *_):
        # Fixed clearance from the attribution strip also works on 230px detail maps.
        for widget, bottom in [
            (self.status_label, 74),
            (self.retry_button, 35),
            (self.focus_button, 35),
            (self.zoom_buttons[0], 139),
            (self.zoom_buttons[1], 87),
        ]:
            hint = dict(widget.pos_hint)
            hint.pop("top", None)
            hint["y"] = dp(bottom) / max(self.height, dp(1))
            widget.pos_hint = hint

    def redraw_clip(self, *_):
        self.clip_start.pos = self.clip_end.pos = self.pos
        self.clip_start.size = self.clip_end.size = self.size
        self.border.rounded_rectangle = (*self.pos, *self.size, dp(22))

    def focus(self, latitude, longitude, zoom=12):
        if self.map._disposed:
            return
        self.focus_center = (latitude, longitude)
        self.map.zoom = max(self.map.map_source.min_zoom, min(self.map.map_source.max_zoom, zoom))
        self.map.center_on(latitude, longitude)
        Clock.schedule_once(lambda _: self.map.center_on(*self.focus_center), 0.35)
