import json
import time
import pytest
from kivy.base import EventLoop
from kivy.clock import Clock
from kivy.core.window import Window
from todaygo.application import TodayGoApp
from todaygo.maps import MOSCOW, MapPanel
from todaygo.theme import Action
from todaygo.screens import AuthScreen, VerifyScreen


class AuthOnlyApp:
    def go_home(self):
        pass

    def go_auth(self):
        pass


@pytest.mark.parametrize("mode", ["login", "register"])
def test_auth_screens_offer_only_password_and_code(mode):
    screen = AuthScreen(app=AuthOnlyApp(), name="auth")
    screen.build(mode)
    buttons = [widget.text for widget in screen.walk() if isinstance(widget, Action)]
    assert not any("Google" in text for text in buttons)
    assert ("Создать аккаунт" if mode == "register" else "Продолжить") in buttons


@pytest.mark.parametrize("delivery", ["email", "development_file"])
def test_verify_explains_actual_code_delivery(delivery):
    screen = VerifyScreen(app=AuthOnlyApp(), name="verify")
    screen.build({"challenge_id": "test-challenge-id", "delivery": delivery})
    text = "\n".join(getattr(widget, "text", "") for widget in screen.walk())
    assert "Письмо уже" not in text
    assert "Google" not in text
    if delivery == "development_file":
        assert "Код сохранён локально" in text
        assert "письма не отправляются" in text
        assert "READ_CODE_WINDOWS.bat" in text
        assert "CONFIGURE_EMAIL_WINDOWS.bat" in text
        assert "Проверьте почту" not in text
    else:
        assert "Проверьте почту" in text
        assert "Спам" in text
        assert "READ_CODE_WINDOWS.bat" not in text


def settle(app, seconds=0.15):
    deadline = time.monotonic() + 10
    clock_deadline = Clock.get_time() + seconds
    while (
        Clock.get_time() < clock_deadline
        or app.busy
        or app._start_event.is_triggered
        or app.manager.transition.is_active
        or any(
            w.map._geometry_trigger.is_triggered
            or any(pin.width == 0 or pin.height == 0 for pin in w.map.event_markers)
            for w in app.root.walk()
            if isinstance(w, MapPanel)
        )
    ):
        EventLoop.idle()
        time.sleep(0.01)
        if time.monotonic() > deadline:
            raise AssertionError("UI operation did not complete")


def click(screen, text):
    button = next(w for w in screen.walk() if isinstance(w, Action) and w.text == text)
    # Keep the pressed state for multiple frames so the press animation runs.
    button.trigger_action(duration=0.10)


def test_all_screens_with_real_api(api_server, monkeypatch):
    url, mail = api_server
    monkeypatch.setenv("TODAYGO_API_URL", url)
    app = TodayGoApp()
    app.root = app.build()
    EventLoop.ensure_window()
    EventLoop.window.add_widget(app.root)
    try:
        settle(app)
        assert app.manager.current == "home"
        assert set(app.manager.screen_names) == {
            "home",
            "list",
            "detail",
            "form",
            "auth",
            "verify",
            "profile",
            "admin",
            "connect",
        }
        app.go_auth()
        auth = app.screens["auth"]
        assert not any(
            "Google" in widget.text for widget in auth.walk() if isinstance(widget, Action)
        )
        auth.build("register")
        for key, value in {
            "name": "Анна Москва",
            "email": "ui@example.com",
            "password": "UiPassword42",
        }.items():
            auth.fields[key].text = value
        auth.organizer.active = True
        click(auth, "Создать аккаунт")
        settle(app)
        assert app.manager.current == "verify"
        verify = app.screens["verify"]
        assert verify.delivery == "development_file"
        verify.code.text = json.loads((mail / f"{verify.challenge}.json").read_text())["code"]
        click(verify, "Войти")
        settle(app)
        assert app.api.user["role"] == "organizer" and app.manager.current == "home"
        app.go_form()
        form = app.screens["form"]
        settle(app)
        assert app.manager.current == "form"
        assert abs(form.mp.map.lat - 55.751244) < 0.001
        form.fields["title"].text = "Встреча на Патриарших"
        form.fields["description"].text = "Встречаемся у пруда, общаемся и гуляем по Москве."
        form.fields["address"].text = "Москва, Патриаршие пруды"
        form.pick(55.7638, 37.5927)
        click(form, "Опубликовать мероприятие")
        settle(app)
        assert app.manager.current == "detail"
        detail = app.screens["detail"]
        eid = detail.event["id"]
        app.go_home()
        settle(app, 0.5)
        markers = app.screens["home"].map_panel.map.event_markers
        assert markers and markers[0].width >= 30 and markers[0].height >= 40
        markers[0].dispatch("on_release")
        settle(app)
        assert app.manager.current == "detail" and detail.event["id"] == eid
        assert detail.event["latitude"] == 55.7638
        click(detail, "Присоединиться")
        settle(app)
        assert detail.event["joined"] and detail.event["attendees"] == 1
        app.go_list("mine")
        settle(app)
        assert app.screens["list"].mode == "mine"
        app.go_detail(eid)
        settle(app)
        click(detail, "Редактировать мероприятие")
        settle(app)
        form.fields["title"].text = "Вечер на Патриарших"
        click(form, "Сохранить изменения")
        settle(app)
        assert detail.event["title"] == "Вечер на Патриарших"
        click(detail, "Удалить мероприятие")
        settle(app)
        from kivy.uix.popup import Popup

        popup = next(w for w in EventLoop.window.children if isinstance(w, Popup))
        click(popup, "Удалить")
        settle(app)
        assert app.api.events(search="Вечер на Патриарших")["total"] == 0
        app.go_profile()
        settle(app)
        click(app.screens["profile"], "Выйти из аккаунта")
        settle(app)
        assert app.api.user is None
        # A supported small window must keep a usable map and reachable controls.
        Window.size = (360, 700)
        settle(app, 0.6)
        home = app.screens["home"]
        assert home.map_panel.map.height >= 220
        assert abs(home.map_panel.map.lat - MOSCOW[0]) < 0.001
        assert abs(home.map_panel.map.lon - MOSCOW[1]) < 0.001
        assert home.cards_scroll.disabled
        for button in (home.map_panel.retry_button, home.map_panel.focus_button):
            assert home.map_panel.y <= button.y < button.top <= home.map_panel.top
        Window.size = (480, 960)
        settle(app, 0.6)
        assert not home.cards_scroll.disabled
        assert home.map_panel.map.height >= 220
        assert abs(home.map_panel.map.lat - MOSCOW[0]) < 0.001
    finally:
        EventLoop.window.remove_widget(app.root)
        app.on_stop()
