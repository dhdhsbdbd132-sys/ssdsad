from datetime import datetime, timedelta, timezone
from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivy.uix.popup import Popup
from kivy.uix.spinner import Spinner
from kivy.uix.checkbox import CheckBox
from kivy.metrics import dp
from todaygo.theme import (
    Panel,
    Action,
    Copy,
    Paragraph,
    Field,
    BG,
    BLUE,
    MUTED,
    WHITE,
    PALE,
    GREEN,
    CATEGORIES,
    CATEGORY_COLORS,
    ROLES,
)
from todaygo.maps import MapPanel, MOSCOW, EventPin

MSK = timezone(timedelta(hours=3))


def date_label(value):
    return (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        .astimezone(MSK)
        .strftime("%d.%m · %H:%M")
    )


def scroll_column(spacing=12):
    scroll = ScrollView(do_scroll_x=False)
    column = BoxLayout(
        orientation="vertical", size_hint_y=None, spacing=dp(spacing), padding=(dp(20), dp(16))
    )
    column.bind(minimum_height=column.setter("height"))
    scroll.add_widget(column)
    return scroll, column


class BaseScreen(Screen):
    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.layout = Panel(fill=BG, radius=0, orientation="vertical")
        self.add_widget(self.layout)

    def reset(self):
        self.layout.clear_widgets()

    def header(self, title, back=True, action=None):
        row = BoxLayout(size_hint_y=None, height=dp(64), spacing=dp(10), padding=(dp(20), dp(10)))
        if back:
            row.add_widget(
                Action(
                    "‹",
                    self.app.go_home,
                    secondary=True,
                    width=dp(40),
                    size_hint_x=None,
                    height=dp(40),
                )
            )
        row.add_widget(Copy(text=title, size=18, bold=True, height=40))
        if action:
            row.add_widget(action)
        self.layout.add_widget(row)

    def nav(self, active):
        row = Panel(
            radius=0, size_hint_y=None, height=dp(68), padding=(dp(12), dp(10)), spacing=dp(8)
        )
        for key, label, callback in [
            ("home", "◎ Карта", self.app.go_home),
            ("list", "≡ Афиша", lambda: self.app.go_list("all")),
            ("mine", "♡ Моё", lambda: self.app.go_list("mine")),
            ("profile", "○ Профиль", self.app.go_profile),
        ]:
            row.add_widget(
                Action(label, callback, secondary=key != active, font_size=dp(11), height=dp(44))
            )
        self.layout.add_widget(row)


class EventCard(Panel):
    def __init__(self, app, event, compact=False, **kwargs):
        super().__init__(
            orientation="vertical",
            size_hint_y=None,
            height=dp(166 if compact else 188),
            padding=dp(15),
            spacing=dp(3),
            **kwargs,
        )
        top = BoxLayout(size_hint_y=None, height=dp(24), spacing=dp(8))
        top.add_widget(
            Copy(
                text=CATEGORIES[event["category"]].upper(),
                size=10,
                bold=True,
                color=CATEGORY_COLORS[event["category"]],
                height=24,
            )
        )
        top.add_widget(
            Copy(
                text=date_label(event["starts_at"]), size=11, color=MUTED, halign="right", height=24
            )
        )
        self.add_widget(top)
        self.add_widget(
            Copy(
                text=event["title"],
                size=16,
                bold=True,
                height=46,
                shorten=True,
                shorten_from="right",
            )
        )
        self.add_widget(
            Copy(
                text=event["address"],
                size=11,
                color=MUTED,
                height=24,
                shorten=True,
                shorten_from="right",
            )
        )
        bottom = BoxLayout(size_hint_y=None, height=dp(39), spacing=dp(12))
        bottom.add_widget(
            Copy(
                text=f"{event['attendees']} / {event['capacity']} участников",
                size=11,
                color=GREEN,
                height=36,
            )
        )
        bottom.add_widget(
            Action(
                "Открыть →",
                lambda: app.go_detail(event["id"]),
                secondary=True,
                width=dp(115),
                size_hint_x=None,
                height=dp(36),
            )
        )
        self.add_widget(bottom)
        if event["joined"] and not compact:
            self.add_widget(Copy(text="✓ Вы участвуете", size=11, color=GREEN, height=18))


class HomeScreen(BaseScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.category = "all"
        self.build()

    def build(self):
        self.reset()
        header = BoxLayout(size_hint_y=None, height=dp(62), padding=(dp(20), dp(9)), spacing=dp(12))
        header.add_widget(Action("→", width=dp(40), height=dp(40), size_hint_x=None))
        header.add_widget(Copy(text="сегодня идём", size=18, bold=True, height=40))
        header.add_widget(
            Copy(
                text="МОСКВА",
                size=10,
                color=MUTED,
                bold=True,
                width=dp(66),
                size_hint_x=None,
                height=40,
            )
        )
        self.layout.add_widget(header)
        intro = BoxLayout(
            orientation="vertical", size_hint_y=None, height=dp(90), padding=(dp(20), 0)
        )
        intro.add_widget(Copy(text="Ваш город. Ваши люди.", size=12, color=MUTED, height=23))
        intro.add_widget(Copy(text="Куда пойдём сегодня?", size=24, bold=True, height=40))
        intro.add_widget(
            Copy(text="Находите события и встречайтесь в Москве", size=11, color=MUTED, height=23)
        )
        self.layout.add_widget(intro)
        search_row = BoxLayout(
            size_hint_y=None, height=dp(59), padding=(dp(20), dp(5)), spacing=dp(8)
        )
        self.search = Field("Название, место или настроение")
        self.search.bind(on_text_validate=lambda *_: self.load())
        search_row.add_widget(self.search)
        search_row.add_widget(
            Action("Найти", self.load, height=dp(48), width=dp(72), size_hint_x=None)
        )
        self.layout.add_widget(search_row)
        filters = ScrollView(size_hint_y=None, height=dp(50), do_scroll_y=False)
        chips = BoxLayout(size_hint_x=None, spacing=dp(7), padding=(dp(20), dp(5)))
        chips.bind(minimum_width=chips.setter("width"))
        self.chips = {}
        for key, title in CATEGORIES.items():
            button = Action(
                title,
                lambda key=key: self.set_category(key),
                secondary=key != self.category,
                size_hint_x=None,
                width=dp(68 if key == "all" else 94),
                height=dp(36),
                font_size=dp(11),
            )
            self.chips[key] = button
            chips.add_widget(button)
        filters.add_widget(chips)
        self.layout.add_widget(filters)
        self.map_panel = MapPanel(size_hint_y=0.60)
        self.layout.add_widget(self.map_panel)
        heading = BoxLayout(size_hint_y=None, height=dp(40), padding=(dp(20), 0))
        self.count = Copy(text="Рядом с вами", size=15, bold=True, height=40)
        heading.add_widget(self.count)
        heading.add_widget(
            Action(
                "Вся афиша →",
                lambda: self.app.go_list("all"),
                secondary=True,
                size_hint_x=None,
                width=dp(118),
                height=dp(32),
                font_size=dp(11),
            )
        )
        self.layout.add_widget(heading)
        self.cards_scroll = ScrollView(size_hint_y=0.40, do_scroll_y=False)
        self.cards = BoxLayout(size_hint_x=None, spacing=dp(12), padding=(dp(20), dp(8)))
        self.cards.bind(minimum_width=self.cards.setter("width"))
        self.cards_scroll.add_widget(self.cards)
        self.layout.add_widget(self.cards_scroll)
        self.nav("home")

    def set_category(self, category):
        self.category = category
        for key, chip in self.chips.items():
            chip.fill = BLUE if key == category else PALE
            chip.color = WHITE if key == category else BLUE
            chip.redraw()
        self.load()

    def load(self):
        params = {
            "search": self.search.text.strip(),
            "page_size": 100,
            "after": datetime.now(timezone.utc).isoformat(),
        }
        if self.category != "all":
            params["category"] = self.category
        self.app.run_api(lambda: self.app.api.events(**params), self.loaded)

    def loaded(self, data):
        self.app.events = data["items"]
        self.map_panel.map.display_events(data["items"], self.app.go_detail)
        self.cards.clear_widgets()
        self.count.text = f"Рядом с вами · {data['total']}"
        for event in data["items"]:
            self.cards.add_widget(
                EventCard(self.app, event, compact=True, size_hint_x=None, width=dp(310))
            )
        if not data["items"]:
            self.cards.add_widget(
                Copy(
                    text="Событий пока нет. Попробуйте другой поиск.",
                    width=dp(340),
                    size_hint_x=None,
                    height=80,
                    color=MUTED,
                )
            )


class ListScreen(BaseScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.mode, self.page = "all", 1

    def build(self, mode):
        self.mode, self.page = mode, 1
        self.reset()
        self.header("Мои события" if mode == "mine" else "Афиша Москвы")
        controls = BoxLayout(size_hint_y=None, height=dp(54), padding=(dp(20), 0), spacing=dp(8))
        if mode == "mine":
            controls.add_widget(
                Action("Я участвую", lambda: self.load(joined=True), secondary=True)
            )
            controls.add_widget(
                Action("Я организую", lambda: self.load(owned=True), secondary=True)
            )
        else:
            self.search = Field("Поиск мероприятий")
            self.search.bind(on_text_validate=lambda *_: self.load())
            controls.add_widget(self.search)
            controls.add_widget(Action("Найти", self.load, width=dp(72), size_hint_x=None))
        self.layout.add_widget(controls)
        if mode == "all":
            date_row = BoxLayout(
                size_hint_y=None, height=dp(64), padding=(dp(20), dp(8)), spacing=dp(8)
            )
            self.day = Field("Дата: ГГГГ-ММ-ДД")
            date_row.add_widget(self.day)
            date_row.add_widget(
                Action("По дате", self.load, secondary=True, width=dp(100), size_hint_x=None)
            )
            self.layout.add_widget(date_row)
        scroll, self.column = scroll_column()
        self.layout.add_widget(scroll)
        page_row = BoxLayout(size_hint_y=None, height=dp(50), padding=(dp(20), 0), spacing=dp(10))
        self.prev = Action("← Назад", lambda: self.change_page(-1), secondary=True)
        self.next = Action("Далее →", lambda: self.change_page(1), secondary=True)
        page_row.add_widget(self.prev)
        page_row.add_widget(self.next)
        self.layout.add_widget(page_row)
        if self.app.api.user and self.app.api.user["role"] in {"organizer", "moderator", "admin"}:
            row = BoxLayout(size_hint_y=None, height=dp(60), padding=(dp(20), dp(6)))
            row.add_widget(Action("＋ Создать мероприятие", lambda: self.app.go_form()))
            self.layout.add_widget(row)
        self.nav("mine" if mode == "mine" else "list")
        self.owned, self.joined = False, mode == "mine"
        self.load()

    def change_page(self, delta):
        self.page += delta
        self.load(keep_page=True)

    def load(self, joined=None, owned=None, keep_page=False):
        if joined is not None:
            self.joined, self.owned = joined, False
        if owned is not None:
            self.owned, self.joined = owned, False
        if not keep_page:
            self.page = 1
        params = {"page": self.page, "page_size": 15}
        if self.mode == "all":
            params["search"] = self.search.text.strip()
            if self.day.text.strip():
                try:
                    date = datetime.strptime(self.day.text.strip(), "%Y-%m-%d").replace(tzinfo=MSK)
                    params.update(
                        after=date.isoformat(),
                        before=(date + timedelta(days=1) - timedelta(microseconds=1)).isoformat(),
                    )
                except ValueError:
                    self.app.notice("Укажите дату в формате ГГГГ-ММ-ДД")
                    return
        elif self.owned:
            params["author_id"] = self.app.api.user["id"]
        elif self.joined:
            params["joined"] = True
        self.app.run_api(lambda: self.app.api.events(**params), self.loaded)

    def loaded(self, data):
        self.column.clear_widgets()
        self.column.add_widget(
            Copy(text=f"Найдено: {data['total']} · страница {data['page']}", size=12, color=MUTED)
        )
        for event in data["items"]:
            self.column.add_widget(EventCard(self.app, event))
        if not data["items"]:
            self.column.add_widget(
                Paragraph(
                    text="Здесь пока пусто. Найдите событие на карте или создайте своё.",
                    color=MUTED,
                )
            )
        self.prev.disabled = self.page <= 1
        self.next.disabled = self.page * data["page_size"] >= data["total"]


class DetailScreen(BaseScreen):
    def show(self, event):
        self.event = event
        self.reset()
        self.header("Мероприятие")
        scroll, column = scroll_column()
        self.layout.add_widget(scroll)
        column.add_widget(
            Copy(
                text=CATEGORIES[event["category"]].upper(),
                size=11,
                bold=True,
                color=CATEGORY_COLORS[event["category"]],
            )
        )
        column.add_widget(Paragraph(text=event["title"], size=25, bold=True))
        column.add_widget(
            Copy(text=date_label(event["starts_at"]) + "  ·  Москва", size=14, color=BLUE)
        )
        column.add_widget(Paragraph(text=event["address"], size=13, color=MUTED))
        mp = MapPanel(size_hint_y=None, height=dp(230))
        mp.focus(event["latitude"], event["longitude"], zoom=14)
        mp.map.display_events([event], lambda *_: None)
        column.add_widget(mp)
        column.add_widget(Paragraph(text=event["description"], size=14))
        column.add_widget(Copy(text=f"Организатор: {event['author_name']}", size=12, color=MUTED))
        column.add_widget(
            Copy(
                text=f"{event['attendees']} из {event['capacity']} мест занято",
                size=14,
                color=GREEN,
                bold=True,
            )
        )
        if event["joined"]:
            column.add_widget(
                Action(
                    "✓ Вы участвуете · Отменить участие",
                    lambda: self.app.run_api(
                        lambda: self.app.api.leave(event["id"]),
                        lambda _: self.app.go_detail(event["id"]),
                    ),
                    secondary=True,
                )
            )
        else:
            column.add_widget(Action("Присоединиться", self.join))
        if event["can_edit"]:
            column.add_widget(
                Action("Редактировать мероприятие", lambda: self.app.go_form(event), secondary=True)
            )
            column.add_widget(Action("Удалить мероприятие", self.confirm_delete, danger=True))
        self.nav("list")

    def join(self):
        if not self.app.require_login():
            return
        self.app.run_api(lambda: self.app.api.join(self.event["id"]), self.show)

    def confirm_delete(self):
        content = BoxLayout(orientation="vertical", spacing=dp(16), padding=dp(18))
        content.add_widget(
            Paragraph(
                text="Удалить мероприятие? Записи об участии тоже будут удалены. Это действие нельзя отменить.",
                size=14,
            )
        )
        row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(10))
        popup = Popup(
            title="Подтверждение удаления",
            title_font="Today",
            size_hint=(0.9, None),
            height=dp(290),
            content=content,
        )
        row.add_widget(Action("Отмена", popup.dismiss, secondary=True))

        def delete():
            popup.dismiss()
            self.app.run_api(
                lambda: self.app.api.delete_event(self.event["id"]), lambda _: self.app.go_home()
            )

        row.add_widget(Action("Удалить", delete, danger=True))
        content.add_widget(row)
        popup.open()


class FormScreen(BaseScreen):
    def build(self, event=None):
        self.event = event
        self.reset()
        self.header("Редактирование" if event else "Новое мероприятие")
        scroll, column = scroll_column()
        self.layout.add_widget(scroll)
        self.fields = {}
        values = event or {}
        for key, label in [
            ("title", "Название"),
            ("description", "Описание"),
            ("address", "Место встречи"),
        ]:
            column.add_widget(Copy(text=label, size=12, bold=True))
            field = Field(
                label,
                text=values.get(key, ""),
                multiline=key == "description",
                height=dp(110 if key == "description" else 48),
            )
            self.fields[key] = field
            column.add_widget(field)
        column.add_widget(Copy(text="Категория", size=12, bold=True))
        self.category = Spinner(
            text=CATEGORIES[values.get("category", "community")],
            values=tuple(v for k, v in CATEGORIES.items() if k != "all"),
            font_name="Today",
            size_hint_y=None,
            height=dp(48),
            background_normal="",
            background_color=BLUE,
        )
        column.add_widget(self.category)
        column.add_widget(Copy(text="Дата и время · московское время (UTC+3)", size=12, bold=True))
        date = (
            datetime.fromisoformat(event["starts_at"]).astimezone(MSK)
            if event
            else datetime.now(MSK) + timedelta(days=1)
        )
        self.fields["date"] = Field("ГГГГ-ММ-ДД ЧЧ:ММ", text=date.strftime("%Y-%m-%d %H:%M"))
        column.add_widget(self.fields["date"])
        column.add_widget(Copy(text="Количество мест", size=12, bold=True))
        self.fields["capacity"] = Field(
            "30", text=str(values.get("capacity", 30)), input_filter="int"
        )
        column.add_widget(self.fields["capacity"])
        self.coords = (values.get("latitude", MOSCOW[0]), values.get("longitude", MOSCOW[1]))
        column.add_widget(Copy(text="Нажмите на карту, чтобы выбрать место", size=12, bold=True))
        self.mp = MapPanel(on_pick=self.pick, size_hint_y=None, height=dp(290))
        self.mp.map.picking = True
        self.mp.focus(*self.coords)
        column.add_widget(self.mp)
        self.coords_label = Copy(text="", size=11, color=MUTED)
        column.add_widget(self.coords_label)
        self.pick(*self.coords)
        column.add_widget(
            Action("Сохранить изменения" if event else "Опубликовать мероприятие", self.save)
        )
        column.add_widget(
            Action(
                "Отмена",
                lambda: self.app.go_detail(event["id"]) if event else self.app.go_home(),
                secondary=True,
            )
        )

    def pick(self, lat, lon):
        self.coords = (lat, lon)
        self.coords_label.text = f"Координаты: {lat:.5f}, {lon:.5f}"
        self.mp.map.clear_markers()
        marker = EventPin(lat=lat, lon=lon)
        self.mp.map.add_marker(marker)
        self.mp.map.event_markers.append(marker)

    def save(self):
        try:
            date = datetime.strptime(self.fields["date"].text.strip(), "%Y-%m-%d %H:%M").replace(
                tzinfo=MSK
            )
            capacity = int(self.fields["capacity"].text)
        except ValueError:
            self.app.notice("Проверьте дату (ГГГГ-ММ-ДД ЧЧ:ММ) и число мест")
            return
        data = {key: self.fields[key].text.strip() for key in ("title", "description", "address")}
        data.update(
            category=next(k for k, v in CATEGORIES.items() if v == self.category.text),
            starts_at=date.isoformat(),
            capacity=capacity,
            latitude=self.coords[0],
            longitude=self.coords[1],
        )
        self.app.run_api(
            lambda: self.app.api.save_event(data, self.event["id"] if self.event else None),
            lambda e: self.app.go_detail(e["id"]),
        )


class AuthScreen(BaseScreen):
    def build(self, mode="login"):
        self.mode = mode
        self.reset()
        self.header("Добро пожаловать", back=True)
        scroll, column = scroll_column(14)
        self.layout.add_widget(scroll)
        column.add_widget(
            Copy(text="СЕГОДНЯ ИДЁМ  /  МОСКВА", size=10, color=BLUE, bold=True, height=35)
        )
        column.add_widget(Paragraph(text="Москва ближе,\nчем кажется.", size=30, bold=True))
        column.add_widget(
            Paragraph(text="Встречайте своих людей.\nОткрывайте новые места.", size=14, color=MUTED)
        )
        card = Panel(orientation="vertical", size_hint_y=None, padding=dp(22), spacing=dp(12))
        card.bind(minimum_height=card.setter("height"))
        column.add_widget(card)
        card.add_widget(
            Copy(
                text="Регистрация" if mode == "register" else "Вход в аккаунт",
                size=20,
                bold=True,
                height=36,
            )
        )
        self.fields = {}
        if mode == "register":
            self.fields["name"] = Field("Ваше имя")
            card.add_widget(self.fields["name"])
        self.fields["email"] = Field("Электронная почта")
        self.fields["password"] = Field("Пароль", password=True)
        card.add_widget(self.fields["email"])
        card.add_widget(self.fields["password"])
        if mode == "register":
            card.add_widget(
                Paragraph(
                    text="Минимум 10 символов: строчная и заглавная буквы, цифра.",
                    size=10,
                    color=MUTED,
                )
            )
            role = BoxLayout(size_hint_y=None, height=dp(42))
            self.organizer = CheckBox(size_hint_x=None, width=dp(36), color=BLUE)
            role.add_widget(self.organizer)
            role.add_widget(Copy(text="Хочу организовывать мероприятия", size=11, height=42))
            card.add_widget(role)
        card.add_widget(
            Action("Создать аккаунт" if mode == "register" else "Продолжить", self.submit)
        )
        card.add_widget(
            Action(
                "Уже есть аккаунт? Войти" if mode == "register" else "Нет аккаунта? Регистрация",
                lambda: self.build("login" if mode == "register" else "register"),
                secondary=True,
            )
        )
        if mode == "login":
            card.add_widget(Action("Войти через Google", self.app.oauth_login, secondary=True))
        column.add_widget(
            Paragraph(
                text="Вход защищён паролем и одноразовым кодом подтверждения.", size=11, color=MUTED
            )
        )

    def submit(self):
        email, password = self.fields["email"].text.strip(), self.fields["password"].text
        if self.mode == "register":
            data = {
                "name": self.fields["name"].text.strip(),
                "email": email,
                "password": password,
                "role": "organizer" if self.organizer.active else "attendee",
            }

            def fn():
                return self.app.api.register(data)
        else:

            def fn():
                return self.app.api.login(email, password)

        self.app.run_api(fn, self.app.go_verify)


class VerifyScreen(BaseScreen):
    def build(self, data):
        self.challenge = data["challenge_id"]
        self.reset()
        self.header("Подтвердите вход")
        scroll, column = scroll_column(18)
        self.layout.add_widget(scroll)
        column.add_widget(Widget(size_hint_y=None, height=dp(45)))
        column.add_widget(Copy(text="Проверьте почту", size=27, bold=True, height=50))
        column.add_widget(
            Paragraph(
                text="Введите шестизначный код подтверждения. Он действует 10 минут.", color=MUTED
            )
        )
        self.code = Field("000000", input_filter="int", font_size=dp(25), height=dp(62))
        column.add_widget(self.code)
        column.add_widget(
            Action(
                "Войти",
                lambda: self.app.run_api(
                    lambda: self.app.api.verify(self.challenge, self.code.text.strip()),
                    lambda _: self.app.go_home(),
                ),
            )
        )
        column.add_widget(
            Action(
                "Получить новый код · Вернуться к входу", lambda: self.app.go_auth(), secondary=True
            )
        )


class ProfileScreen(BaseScreen):
    def build(self):
        self.reset()
        self.header("Профиль", back=False)
        scroll, column = scroll_column()
        self.layout.add_widget(scroll)
        user = self.app.api.user
        if user:
            column.add_widget(Copy(text=user["name"], size=26, bold=True, height=50))
            column.add_widget(Copy(text=user["email"], size=13, color=MUTED))
            column.add_widget(Copy(text=ROLES[user["role"]], size=13, color=BLUE, bold=True))
            column.add_widget(
                Action("Мои мероприятия", lambda: self.app.go_list("mine"), secondary=True)
            )
            if user["role"] in {"organizer", "moderator", "admin"}:
                column.add_widget(Action("＋ Создать мероприятие", lambda: self.app.go_form()))
            if user["role"] == "admin":
                column.add_widget(
                    Action("Управление пользователями", self.app.go_admin, secondary=True)
                )
            column.add_widget(Action("Выйти из аккаунта", self.app.logout, danger=True))
        else:
            column.add_widget(Paragraph(text="Ваши события начинаются здесь.", size=26, bold=True))
            column.add_widget(Action("Войти или зарегистрироваться", self.app.go_auth))
        column.add_widget(Widget(size_hint_y=None, height=dp(15)))
        column.add_widget(Copy(text="Подключение к серверу", size=16, bold=True))
        self.server = Field("https://api.example.com", text=self.app.api.base_url)
        column.add_widget(self.server)
        column.add_widget(Action("Сохранить адрес API", self.set_server, secondary=True))
        column.add_widget(
            Paragraph(
                text="Сегодня идём · 1.0\nМероприятия, люди и любимый город.", size=11, color=MUTED
            )
        )
        self.nav("profile")

    def set_server(self):
        from todaygo.api import ApiClient, ApiError

        if self.app.api.user:
            self.app.notice("Сначала выйдите из аккаунта")
            return
        try:
            self.app.api = ApiClient(self.server.text)
        except ApiError as exc:
            self.app.notice(str(exc))
            return
        self.app.save_server()
        self.app.go_home()


class AdminScreen(BaseScreen):
    def build(self, data):
        self.reset()
        self.header("Пользователи")
        scroll, column = scroll_column()
        self.layout.add_widget(scroll)
        column.add_widget(Copy(text="Управление ролями · страница 1", size=12, color=MUTED))
        for user in data:
            panel = Panel(
                orientation="vertical",
                size_hint_y=None,
                height=dp(145),
                padding=dp(14),
                spacing=dp(6),
            )
            panel.add_widget(Copy(text=user["name"], size=15, bold=True))
            panel.add_widget(Copy(text=user["email"], size=11, color=MUTED))
            row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
            spinner = Spinner(
                text=ROLES[user["role"]],
                values=tuple(ROLES.values()),
                font_name="Today",
                background_normal="",
                background_color=BLUE,
            )
            row.add_widget(spinner)

            def apply(user=user, spinner=spinner):
                role = next(k for k, v in ROLES.items() if v == spinner.text)
                self.app.run_api(
                    lambda: self.app.api.request(
                        "PATCH", f"/admin/users/{user['id']}/role", {"role": role}
                    ),
                    lambda _: self.app.go_admin(),
                )

            row.add_widget(
                Action(
                    "Сохранить",
                    apply,
                    secondary=True,
                    width=dp(110),
                    size_hint_x=None,
                    height=dp(40),
                )
            )
            panel.add_widget(row)
            column.add_widget(panel)
