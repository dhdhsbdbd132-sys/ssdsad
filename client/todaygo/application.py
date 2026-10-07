import json
import os
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.screenmanager import ScreenManager, NoTransition
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.popup import Popup
from kivy.utils import platform
from todaygo.api import ApiClient, ApiError
from todaygo.theme import Copy, Action, BG, BLUE
from todaygo.screens import (
    HomeScreen,
    ListScreen,
    DetailScreen,
    FormScreen,
    AuthScreen,
    VerifyScreen,
    ProfileScreen,
    AdminScreen,
)


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
            Window.size = (430, 900)
        self.executor = ThreadPoolExecutor(max_workers=1)
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
        self.manager = ScreenManager(transition=NoTransition())
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
        self.status = Copy(text="", size=10, color=BLUE, height=20, halign="center")
        root.add_widget(self.status)
        Window.bind(on_keyboard=self.key)
        Clock.schedule_once(lambda _: self.go_home(), 0.1)
        if not self.map_offline:
            import threading

            threading.Thread(target=self.check_map, daemon=True).start()
        return root

    def check_map(self):
        import requests

        try:
            response = requests.get(
                "https://a.basemaps.cartocdn.com/light_all/0/0/0.png", timeout=4
            )
            response.raise_for_status()
        except requests.RequestException:
            Clock.schedule_once(lambda _: self.fallback_map(), 0)

    def fallback_map(self):
        self.map_offline = True
        for screen in self.screens.values():
            for widget in screen.walk():
                from todaygo.maps import MapPanel

                if isinstance(widget, MapPanel):
                    widget.map.use_offline()
                    widget.attribution_label.text = "Схема Москвы · офлайн · не для навигации"

    def run_api(self, fn, callback):
        if self.busy:
            return
        self.busy = True
        self.status.text = "Загружаем…"
        self.manager.disabled = True
        future = self.executor.submit(fn)

        def finished(result):
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
        self.busy = False
        self.status.text = ""
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
        content.add_widget(Copy(text=text, size=13, height=140))
        popup = Popup(
            title="Сегодня идём",
            title_font="Today",
            content=content,
            size_hint=(0.9, None),
            height=dp(290),
        )
        content.add_widget(Action("Понятно", popup.dismiss))
        popup.open()

    def require_login(self):
        if self.api.user:
            return True
        self.go_auth()
        return False

    def switch(self, name):
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
        screen.layout.add_widget(
            Copy(
                text="Завершите вход в браузере.\nЗатем вернитесь в приложение.",
                size=16,
                height=150,
                halign="center",
            )
        )
        screen.layout.add_widget(Action("Отмена", self.cancel_oauth, secondary=True))
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
        if self.poll_event:
            self.poll_event.cancel()
        self.api.clear_tokens()
        self.executor.shutdown(wait=False, cancel_futures=True)
