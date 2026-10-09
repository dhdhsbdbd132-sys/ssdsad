"""The real Kivy demo performs CRUD with all HTTP requests forbidden."""

import json
import time

from kivy.base import EventLoop
from kivy.uix.popup import Popup
import requests

import todaygo.application as application
from todaygo.application import TodayGoApp
from todaygo.demo import DemoClient
from todaygo.maps import MapPanel
from todaygo.theme import Action, Field


def settle(app, seconds=0.18):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline or app.busy:
        EventLoop.idle()
        time.sleep(0.01)
        if time.monotonic() > deadline + 8:
            raise AssertionError("Offline UI operation did not finish")


def click(container, text):
    button = next(w for w in container.walk() if isinstance(w, Action) and w.text == text)
    assert not button.disabled
    button.trigger_action(duration=0.1)


def prepare(monkeypatch, tmp_path, *, demo=True):
    monkeypatch.setattr(TodayGoApp, "user_data_dir", property(lambda _: str(tmp_path)))
    monkeypatch.delenv("TODAYGO_API_URL", raising=False)
    monkeypatch.delenv("TODAYGO_MAP_MODE", raising=False)
    if demo:
        monkeypatch.setenv("TODAYGO_DEMO", "1")
    else:
        monkeypatch.delenv("TODAYGO_DEMO", raising=False)
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("The standalone demo attempted an HTTP request")

    monkeypatch.setattr(requests.Session, "request", forbidden)
    app = TodayGoApp()
    app.root = app.build()
    EventLoop.ensure_window()
    EventLoop.window.add_widget(app.root)
    settle(app)
    return app, calls


def dispose(app):
    app.on_stop()
    EventLoop.window.remove_widget(app.root)


def test_demo_ui_crud_join_filters_and_login_without_any_http(monkeypatch, tmp_path):
    app, calls = prepare(monkeypatch, tmp_path)
    try:
        assert app.demo_mode and app.manager.current == "home"
        assert not app.connection_required and len(app.events) == 6
        home = app.screens["home"]
        assert "ДЕМО · БЕЗ СЕРВЕРА" in "\n".join(getattr(w, "text", "") for w in home.walk())
        assert home.map_panel.map.offline and home.map_panel.map._forced_offline
        assert home.map_panel.map._startup_event is None
        assert home.map_panel.retry_button.disabled

        home.search.text = "Патриарших"
        click(home, "Найти")
        settle(app)
        assert len(app.events) == 1
        assert "Патриарших" in app.events[0]["title"]
        home.search.text = ""
        home.set_category("music")
        settle(app)
        assert len(app.events) == 1 and app.events[0]["category"] == "music"

        app.go_form()
        form = app.screens["form"]
        settle(app)
        form.fields["title"].text = "Локальная встреча на Патриарших"
        form.fields["description"].text = "Встречаемся у пруда и гуляем по Москве без сервера."
        form.fields["address"].text = "Москва, Патриаршие пруды"
        form.pick(55.7638, 37.5927)
        click(form, "Опубликовать мероприятие")
        settle(app)
        assert app.manager.current == "detail"
        detail = app.screens["detail"]
        event_id = detail.event["id"]
        assert detail.event["can_edit"] and detail.event["latitude"] == 55.7638
        click(detail, "Присоединиться")
        settle(app)
        assert detail.event["joined"] and detail.event["attendees"] == 1
        click(detail, "✓ Вы участвуете · Отменить участие")
        settle(app)
        assert not detail.event["joined"] and detail.event["attendees"] == 0
        click(detail, "Редактировать мероприятие")
        settle(app)
        form.fields["title"].text = "Обновлённая локальная встреча"
        click(form, "Сохранить изменения")
        settle(app)
        assert detail.event["title"] == "Обновлённая локальная встреча"
        restored = DemoClient(tmp_path / "demo/events.json")
        assert restored.event(event_id)["title"] == detail.event["title"]

        app.go_list("mine")
        settle(app)
        click(app.screens["list"], "Я организую")
        settle(app)
        assert "Обновлённая локальная встреча" in "\n".join(
            getattr(w, "text", "") for w in app.screens["list"].walk()
        )
        app.go_detail(event_id)
        settle(app)
        click(detail, "Удалить мероприятие")
        settle(app)
        popup = next(w for w in EventLoop.window.children if isinstance(w, Popup))
        assert app.api.event(event_id)  # Confirmation has not deleted anything yet.
        click(popup, "Удалить")
        settle(app)
        assert app.api.events(search="Обновлённая локальная встреча")["total"] == 0

        app.go_profile()
        settle(app)
        profile_text = "\n".join(getattr(w, "text", "") for w in app.screens["profile"].walk())
        assert "ДЕМО · БЕЗ СЕРВЕРА" in profile_text and "Локальный тестовый аккаунт" in profile_text
        click(app.screens["profile"], "Выйти из аккаунта")
        settle(app)
        assert app.api.user is None and app.manager.current == "auth"
        auth = app.screens["auth"]
        assert not any(isinstance(w, Field) for w in auth.walk())
        click(auth, "Войти в тестовую версию")
        settle(app)
        assert app.api.user["role"] == "organizer" and app.manager.current == "home"
        assert all(w.map._forced_offline for w in app.root.walk() if isinstance(w, MapPanel))
        assert not calls
    finally:
        dispose(app)


def test_phone_can_choose_demo_remember_it_and_return_to_server_without_requests(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(application, "platform", "android")
    saved = {"api_url": "https://api.example.test", "allow_private_http": False}
    app, calls = prepare(monkeypatch, tmp_path, demo=False)
    try:
        assert app.manager.current == "connect"
        (tmp_path / "settings.json").write_text(json.dumps(saved))
        app._settings = saved.copy()
        click(app.screens["connect"], "Открыть тестовую версию")
        settle(app)
        assert app.demo_mode and app.manager.current == "home"
        persisted = json.loads((tmp_path / "settings.json").read_text())
        assert persisted == {**saved, "mode": "demo"}
        app.api.save_event(
            {
                **{
                    key: app.api.event(1)[key]
                    for key in (
                        "title",
                        "description",
                        "category",
                        "starts_at",
                        "address",
                        "latitude",
                        "longitude",
                        "capacity",
                    )
                },
                "title": "Сохранено после перезапуска",
            }
        )
    finally:
        dispose(app)

    restored, restored_calls = prepare(monkeypatch, tmp_path, demo=False)
    try:
        assert restored.demo_mode and restored.manager.current == "home"
        assert restored.api.events(search="Сохранено после перезапуска")["total"] == 1
        old_map = restored.screens["home"].map_panel.map
        restored.go_profile()
        settle(restored)
        click(restored.screens["profile"], "Подключиться к серверу")
        settle(restored)
        assert not restored.demo_mode and restored.manager.current == "connect"
        assert restored.connection_required and restored.api.user is None
        assert restored.screens["connect"].server.text == saved["api_url"]
        assert old_map._disposed
        assert json.loads((tmp_path / "settings.json").read_text()) == saved
        assert not calls and not restored_calls
    finally:
        dispose(restored)
