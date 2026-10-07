import json
import os
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from kivy.animation import Animation
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.screenmanager import ScreenManager, FadeTransition, NoTransition
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget
from kivy.graphics import Color, RoundedRectangle
from kivy.properties import BooleanProperty, NumericProperty
from kivy.utils import platform
from todaygo.api import ApiClient, ApiError
from todaygo.motion import reduced_motion
from todaygo.theme import Paragraph, Action, BG, BLUE, Hero
from todaygo.screens import (
    HomeScreen,
    ListScreen,
    DetailScreen,
    FormScreen,
    AuthScreen,
    VerifyScreen,
    ProfileScreen,
    AdminScreen,
    styled_popup,
)


class LoadingStrip(Widget):
    active = BooleanProperty(False)
    phase = NumericProperty(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas:
            self.tint = Color(*BLUE[:3], 0)
            self.bar = RoundedRectangle(radius=[dp(2)])
        self.bind(pos=self.redraw, size=self.redraw, phase=self.redraw, active=self.toggle)

    def redraw(self, *_):
        width = self.width if reduced_motion() else self.width * 0.24
        self.bar.size = (width, self.height)
        self.bar.pos = (self.x + (self.width - width) * self.phase, self.y)
        self.tint.a = 0.9 if self.active else 0

    def toggle(self, *_):
        Animation.cancel_all(self, "phase")
        self.phase = 0
        if self.active and not reduced_motion():
            animation = Animation(phase=1, duration=0.85, t="in_out_sine") + Animation(
                phase=0, duration=0.85, t="in_out_sine"
            )
            animation.repeat = True
            animation.start(self)
        self.redraw()


class TodayGoApp(App):
    title = "Сегодня идём"

    @property
    def user_data_dir(self):
        if platform == "android":
            return super().user_data_dir
        path = Path(__file__).resolve().parents[2] / ".data/client"
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def build(self):
        Window.clearcolor = BG
        if platform != "android":
            Window.size = (480, 960)
            Window.minimum_width = dp(360)
            Window.minimum_height = dp(700)
        self.executor = ThreadPoolExecutor(max_workers=1)
        self._stopping = False
        self.busy = False
        self.events = []
        self.poll_event = None
        self.map_offline = os.environ.get("TODAYGO_MAP_MODE") == "offline"
        config = Path(self.user_data_dir) / "settings.json"
        base = "http://127.0.0.1:8000"
        if config.exists():
            try:
                base = json.loads(config.read_text()).get("api_url", base)
            except (ValueError, OSError):
                pass
        self.api = ApiClient(os.environ.get("TODAYGO_API_URL", base))
        root = BoxLayout(orientation="vertical")
        self.manager = ScreenManager(
            transition=NoTransition() if reduced_motion() else FadeTransition(duration=0.20)
        )
        self.screens = {}
        for key, cls in [
            ("home", HomeScreen),
            ("list", ListScreen),
            ("detail", DetailScreen),
            ("form", FormScreen),
            ("auth", AuthScreen),
            ("verify", VerifyScreen),
            ("profile", ProfileScreen),
            ("admin", AdminScreen),
        ]:
            screen = cls(app=self, name=key)
            self.screens[key] = screen
            self.manager.add_widget(screen)
        root.add_widget(self.manager)
        self.status = LoadingStrip(size_hint_y=None, height=dp(3))
        root.add_widget(self.status)
        Window.bind(on_keyboard=self.key)
        self._start_event = Clock.schedule_once(lambda _: self.go_home(), 0.1)
        return root

    def run_api(self, fn, callback):
        if self.busy or self._stopping:
            return
        self.busy = True
        self.status.active = True
        self.manager.disabled = True
        future = self.executor.submit(fn)

        def finished(result):
            if self._stopping:
                return
            try:
                data = result.result()
                error = None
            except ApiError as exc:
                data = None
                error = exc
            except Exception:
                data = None
                error = ApiError("Не удалось выполнить действие")
            Clock.schedule_once(lambda _: self.complete(data, error, callback), 0)

        future.add_done_callback(finished)

    def complete(self, data, error, callback):
        if self._stopping:
            return
        self.busy = False
        self.status.active = False
        self.manager.disabled = False
        if error:
            if (
                error.status == 401
                and not self.api.user
                and self.manager.current not in {"auth", "verify"}
            ):
                self.go_auth()
            self.notice(str(error))
            return
        callback(data)

    def notice(self, text):
        content = BoxLayout(orientation="vertical", spacing=dp(15), padding=dp(14))
        content.add_widget(Paragraph(text=text, size=13))
        popup = styled_popup("Сегодня идём", content)
        content.add_widget(Action("Понятно", popup.dismiss))
        popup.open()

    def require_login(self):
        if self.api.user:
            return True
        self.go_auth()
        return False

    def switch(self, name):
        if self.manager.current == name:
            return
        if self.manager.transition.is_active:
            self.manager.transition.stop()
        self.manager.current = name

    def go_home(self):
        self.switch("home")
        self.screens["home"].load()

    def go_list(self, mode):
        if mode == "mine" and not self.require_login():
            return
        self.switch("list")
        self.screens["list"].build(mode)

    def go_detail(self, event_id):
        self.run_api(
            lambda: self.api.event(event_id),
            lambda data: (self.screens["detail"].show(data), self.switch("detail")),
        )

    def go_form(self, event=None):
        if not self.require_login():
            return
        if self.api.user["role"] not in {"organizer", "moderator", "admin"}:
            self.notice("Создавать события может организатор")
            return
        self.screens["form"].build(event)
        self.switch("form")

    def go_auth(self):
        self.screens["auth"].build()
        self.switch("auth")

    def go_verify(self, data):
        self.screens["verify"].build(data)
        self.switch("verify")

    def go_profile(self):
        self.screens["profile"].build()
        self.switch("profile")

    def go_admin(self):
        self.run_api(
            lambda: self.api.request("GET", "/admin/users"),
            lambda data: (self.screens["admin"].build(data), self.switch("admin")),
        )

    def logout(self):
        self.run_api(self.api.logout, lambda _: self.go_home())

    def save_server(self):
        (Path(self.user_data_dir) / "settings.json").write_text(
            json.dumps({"api_url": self.api.base_url})
        )

    def oauth_login(self):
        self.run_api(lambda: self.api.request("GET", "/auth/oauth/start"), self.oauth_started)

    def oauth_started(self, data):
        if self.poll_event:
            self.poll_event.cancel()
        self.oauth = data
        self.poll_count = 0
        if platform == "android":
            from jnius import autoclass

            Intent = autoclass("android.content.Intent")
            Uri = autoclass("android.net.Uri")
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            activity.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(data["authorization_url"])))
        else:
            webbrowser.open(data["authorization_url"])
        # A dedicated wait screen makes browser return behavior visible and cancellable.
        screen = self.screens["verify"]
        screen.reset()
        screen.header("Вход через Google")
        from todaygo.screens import scroll_column

        scroll, column = scroll_column()
        screen.layout.add_widget(scroll)
        column.add_widget(
            Hero(
                "До встречи\nв приложении.",
                "Завершите вход в браузере, затем вернитесь сюда.",
                eyebrow="ВХОД ЧЕРЕЗ GOOGLE",
                category="culture",
                height=230,
            )
        )
        column.add_widget(Action("Отмена", self.cancel_oauth, secondary=True))
        self.switch("verify")
        self.poll_event = Clock.schedule_interval(self.oauth_poll, 5)

    def cancel_oauth(self):
        if self.poll_event:
            self.poll_event.cancel()
            self.poll_event = None
        self.go_auth()

    def oauth_poll(self, _):
        if self.busy:
            return
        self.poll_count += 1
        if self.poll_count > 110:
            self.cancel_oauth()
            self.notice("Время OAuth-входа истекло")
            return
        self.run_api(
            lambda: self.api.request(
                "POST",
                "/auth/oauth/poll",
                {"state": self.oauth["state"], "poll_key": self.oauth["poll_key"]},
            ),
            self.oauth_polled,
        )

    def oauth_polled(self, data):
        if data["status"] == "complete":
            self.poll_event.cancel()
            self.poll_event = None
            self.go_verify(data)

    def key(self, window, key, *_):
        if key == 27 and self.manager.current != "home":
            if self.poll_event:
                self.poll_event.cancel()
                self.poll_event = None
            self.go_home()
            return True
        return False

    def on_pause(self):
        return True

    def on_stop(self):
        self._stopping = True
        self._start_event.cancel()
        if self.poll_event:
            self.poll_event.cancel()
        self.api.clear_tokens()
        self.status.active = False
        Window.unbind(on_keyboard=self.key)
        from todaygo.maps import MapPanel

        for screen in self.screens.values():
            for widget in screen.walk():
                if isinstance(widget, MapPanel):
                    widget.map.dispose()
        self.executor.shutdown(wait=False, cancel_futures=True)
