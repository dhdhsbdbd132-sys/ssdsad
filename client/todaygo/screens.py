from datetime import datetime, timedelta, timezone

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.checkbox import CheckBox
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView

from todaygo.maps import MOSCOW, EventPin, MapPanel
from todaygo.motion import enter
from todaygo.theme import (
    Action,
    Avatar,
    Badge,
    BG,
    BLUE,
    CATEGORIES,
    Copy,
    Field,
    GREEN,
    Hero,
    INK,
    MUTED,
    NavAction,
    PALE,
    Panel,
    Paragraph,
    ROLES,
    Select,
    SURFACE,
    SURFACE_HIGH,
)

MSK = timezone(timedelta(hours=3))


def date_label(value):
    return (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        .astimezone(MSK)
        .strftime("%d.%m · %H:%M")
    )


def scroll_column(spacing=14):
    scroll = ScrollView(
        do_scroll_x=False,
        bar_width=dp(3),
        bar_color=(*BLUE[:3], 0.45),
        bar_inactive_color=(0, 0, 0, 0),
    )
    column = BoxLayout(
        orientation="vertical", size_hint_y=None, spacing=dp(spacing), padding=(dp(20), dp(16))
    )
    column.bind(minimum_height=column.setter("height"))
    scroll.add_widget(column)
    return scroll, column


def section(title, subtitle=""):
    box = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(55 if subtitle else 32))
    box.add_widget(Copy(text=title, size=18, bold=True, height=32))
    if subtitle:
        box.add_widget(Copy(text=subtitle, size=11, color=MUTED, height=23))
    return box


def form_card(spacing=12):
    card = Panel(
        orientation="vertical", size_hint_y=None, padding=dp(18), spacing=dp(spacing), radius=24
    )
    card.bind(minimum_height=card.setter("height"))
    return card


def labeled_field(column, label, hint, **kwargs):
    column.add_widget(Copy(text=label, size=11, bold=True, color=MUTED, height=22))
    field = Field(hint, **kwargs)
    column.add_widget(field)
    return field


def styled_popup(title, content, height=310):
    return Popup(
        title=title,
        title_font="Today",
        title_size=dp(17),
        title_color=INK,
        separator_color=BLUE,
        separator_height=dp(1),
        background="",
        background_color=SURFACE,
        overlay_color=(0.02, 0.03, 0.07, 0.8),
        size_hint=(0.92, None),
        height=dp(height),
        content=content,
    )


class BaseScreen(Screen):
    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.layout = Panel(fill=BG, radius=0, orientation="vertical")
        self.add_widget(self.layout)

    def reset(self):
        for widget in self.layout.walk():
            if isinstance(widget, MapPanel):
                widget.map.dispose()
        self.layout.clear_widgets()

    def on_enter(self, *_):
        enter(self.layout, offset=0)

    def header(self, title, back=True, action=None):
        row = BoxLayout(size_hint_y=None, height=dp(68), spacing=dp(12), padding=(dp(20), dp(12)))
        if back:
            row.add_widget(
                Action(
                    "‹",
                    self.app.go_home,
                    secondary=True,
                    width=dp(42),
                    size_hint_x=None,
                    height=dp(42),
                )
            )
        else:
            row.add_widget(Avatar("→", size=42))
        row.add_widget(Copy(text=title, size=18, bold=True, height=42))
        if action:
            row.add_widget(action)
        self.layout.add_widget(row)

    def nav(self, active):
        outer = BoxLayout(size_hint_y=None, height=dp(80), padding=(dp(16), dp(8)))
        row = Panel(radius=24, padding=dp(6), spacing=dp(4), fill=SURFACE_HIGH)
        for key, label, callback in [
            ("home", "◎ Карта", self.app.go_home),
            ("list", "≡ Афиша", lambda: self.app.go_list("all")),
            ("mine", "♡ Моё", lambda: self.app.go_list("mine")),
            ("profile", "○ Профиль", self.app.go_profile),
        ]:
            row.add_widget(NavAction(label, callback, active=key == active, height=dp(48)))
        outer.add_widget(row)
        self.layout.add_widget(outer)


class EventCard(Panel):
    def __init__(self, app, event, compact=False, **kwargs):
        super().__init__(
            orientation="vertical",
            size_hint_y=None,
            height=dp(180 if compact else 204),
            padding=dp(16),
            spacing=dp(5),
            radius=24,
            **kwargs,
        )
        top = BoxLayout(size_hint_y=None, height=dp(28), spacing=dp(8))
        top.add_widget(Badge(CATEGORIES[event["category"]], category=event["category"]))
        top.add_widget(
            Copy(
                text=date_label(event["starts_at"]), size=10, color=MUTED, halign="right", height=28
            )
        )
        self.add_widget(top)
        self.add_widget(
            Copy(
                text=event["title"],
                size=17,
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
                height=22,
                shorten=True,
                shorten_from="right",
            )
        )
        bottom = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(8))
        bottom.add_widget(
            Copy(
                text=f"{event['attendees']} / {event['capacity']} участников",
                size=10,
                color=GREEN,
                height=38,
            )
        )
        bottom.add_widget(
            Action(
                "Открыть →",
                lambda: app.go_detail(event["id"]),
                secondary=True,
                width=dp(110),
                size_hint_x=None,
                height=dp(38),
                font_size=dp(11),
            )
        )
        self.add_widget(bottom)
        if not compact:
            self.add_widget(
                Copy(
                    text="✓ Вы участвуете" if event["joined"] else "Новые места. Новые знакомства.",
                    size=10,
                    color=GREEN if event["joined"] else MUTED,
                    height=18,
                )
            )


class HomeScreen(BaseScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.category = "all"
        self.build()

    def build(self):
        self.reset()
        header = BoxLayout(
            size_hint_y=None, height=dp(64), padding=(dp(20), dp(10)), spacing=dp(12)
        )
        header.add_widget(Avatar("→", size=42))
        header.add_widget(Copy(text="сегодня идём", size=19, bold=True, height=42))
        header.add_widget(Badge("МОСКВА", width=dp(84), category="sport"))
        self.layout.add_widget(header)
        intro = BoxLayout(size_hint_y=None, height=dp(110), padding=(dp(20), 0))
        intro.add_widget(
            Hero(
                "Москва зовёт.",
                "Выбирайте место. Находите своих.",
                eyebrow="ГОРОД ПОЛОН ВОЗМОЖНОСТЕЙ",
                height=110,
                compact=True,
            )
        )
        self.layout.add_widget(intro)
        search_row = BoxLayout(
            size_hint_y=None, height=dp(62), padding=(dp(20), dp(8)), spacing=dp(8)
        )
        self.search = Field("Событие, место или настроение", height=dp(46))
        self.search.bind(on_text_validate=lambda *_: self.load())
        search_row.add_widget(self.search)
        search_row.add_widget(
            Action("Найти", self.load, height=dp(46), width=dp(76), size_hint_x=None)
        )
        self.layout.add_widget(search_row)
        filters = ScrollView(size_hint_y=None, height=dp(48), do_scroll_y=False, bar_width=0)
        chips = BoxLayout(size_hint_x=None, spacing=dp(8), padding=(dp(20), dp(5)))
        chips.bind(minimum_width=chips.setter("width"))
        self.chips = {}
        for key, title in CATEGORIES.items():
            button = Action(
                title,
                lambda key=key: self.set_category(key),
                secondary=key != self.category,
                size_hint_x=None,
                width=dp(64 if key == "all" else 100),
                height=dp(36),
                font_size=dp(11),
            )
            self.chips[key] = button
            chips.add_widget(button)
        filters.add_widget(chips)
        self.layout.add_widget(filters)
        map_wrap = BoxLayout(padding=(dp(20), dp(6)))
        self.map_panel = MapPanel()
        map_wrap.add_widget(self.map_panel)
        self.layout.add_widget(map_wrap)
        heading = BoxLayout(size_hint_y=None, height=dp(42), padding=(dp(20), dp(4)))
        self.count = Copy(text="События рядом", size=16, bold=True, height=34)
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
        self.cards_scroll = ScrollView(
            size_hint_y=None, height=dp(198), do_scroll_y=False, bar_width=0
        )
        self.cards = BoxLayout(size_hint_x=None, spacing=dp(12), padding=(dp(20), dp(8)))
        self.cards.bind(minimum_width=self.cards.setter("width"))
        self.cards_scroll.add_widget(self.cards)
        self.layout.add_widget(self.cards_scroll)
        self.nav("home")
        self.bind(size=self.fit_preview)
        self.fit_preview()

    def fit_preview(self, *_):
        # Keep the map usable on phone displays and small desktop windows.
        # Events remain available through their markers and the full list.
        show = self.height >= dp(880)
        self.cards_scroll.height = dp(198) if show else 0
        self.cards_scroll.opacity = 1 if show else 0
        self.cards_scroll.disabled = not show

    def set_category(self, category):
        self.category = category
        for key, chip in self.chips.items():
            chip.fill = BLUE if key == category else PALE
            chip.color = BG if key == category else INK
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
        self.count.text = f"События рядом · {data['total']}"
        for index, event in enumerate(data["items"]):
            card = EventCard(self.app, event, compact=True, size_hint_x=None, width=dp(316))
            self.cards.add_widget(card)
            if index < 6:
                enter(card, delay=index * 0.045, offset=0)
        if not data["items"]:
            self.cards.add_widget(
                Hero(
                    "Немного тишины.",
                    "Попробуйте другой поиск или категорию.",
                    eyebrow="СОБЫТИЙ ПОКА НЕТ",
                    compact=True,
                    height=180,
                    width=dp(340),
                    size_hint_x=None,
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
        controls = BoxLayout(
            size_hint_y=None, height=dp(56), padding=(dp(20), dp(4)), spacing=dp(8)
        )
        if mode == "mine":
            controls.add_widget(
                Action("Я участвую", lambda: self.load(joined=True), secondary=True)
            )
            controls.add_widget(
                Action("Я организую", lambda: self.load(owned=True), secondary=True)
            )
        else:
            self.search = Field("Что хочется найти?")
            self.search.bind(on_text_validate=lambda *_: self.load())
            controls.add_widget(self.search)
            controls.add_widget(Action("Найти", self.load, width=dp(76), size_hint_x=None))
        self.layout.add_widget(controls)
        if mode == "all":
            date_row = BoxLayout(
                size_hint_y=None, height=dp(60), padding=(dp(20), dp(6)), spacing=dp(8)
            )
            self.day = Field("Дата: ГГГГ-ММ-ДД")
            date_row.add_widget(self.day)
            date_row.add_widget(
                Action("По дате", self.load, secondary=True, width=dp(104), size_hint_x=None)
            )
            self.layout.add_widget(date_row)
        scroll, self.column = scroll_column()
        self.layout.add_widget(scroll)
        page_row = BoxLayout(
            size_hint_y=None, height=dp(54), padding=(dp(20), dp(3)), spacing=dp(10)
        )
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
            Hero(
                "Ваши планы." if self.mode == "mine" else "Выйдем из дома?",
                f"Найдено: {data['total']} · страница {data['page']}",
                eyebrow="ЛЮДИ. МЕСТА. МОМЕНТЫ.",
                height=116,
                compact=True,
            )
        )
        for index, event in enumerate(data["items"]):
            card = EventCard(self.app, event)
            self.column.add_widget(card)
            if index < 8:
                enter(card, delay=index * 0.045, offset=0)
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
            Hero(
                event["title"],
                event["address"],
                eyebrow=CATEGORIES[event["category"]].upper(),
                category=event["category"],
                height=180,
            )
        )
        if len(event["title"]) > 48:
            column.add_widget(Paragraph(text=event["title"], size=20, bold=True))
        summary = form_card()
        summary.add_widget(
            section("Сохраняйте момент", "Хорошие встречи начинаются с одного решения.")
        )
        summary.add_widget(
            Copy(
                text=date_label(event["starts_at"]) + "  ·  Москва", size=15, color=BLUE, bold=True
            )
        )
        summary.add_widget(Paragraph(text=event["description"], size=14))
        summary.add_widget(Copy(text=f"Организатор: {event['author_name']}", size=12, color=MUTED))
        summary.add_widget(
            Badge(f"{event['attendees']} из {event['capacity']} мест занято", category="sport")
        )
        column.add_widget(summary)
        column.add_widget(section("Место встречи", event["address"]))
        mp = MapPanel(size_hint_y=None, height=dp(260))
        mp.focus(event["latitude"], event["longitude"], zoom=14)
        mp.map.display_events([event], lambda *_: None)
        column.add_widget(mp)
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
        popup = styled_popup("Подтверждение удаления", content)
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
        column.add_widget(
            Hero(
                "Соберите своих.",
                "Придумайте встречу, на которую хочется прийти.",
                eyebrow="ВАША ИДЕЯ. ВАШ ГОРОД.",
                height=132,
                compact=True,
            )
        )
        self.fields = {}
        values = event or {}
        basics = form_card()
        basics.add_widget(section("01  О мероприятии"))
        for key, label in [
            ("title", "Название"),
            ("description", "Описание"),
            ("address", "Место встречи"),
        ]:
            self.fields[key] = labeled_field(
                basics,
                label,
                label,
                text=values.get(key, ""),
                multiline=key == "description",
                height=dp(110 if key == "description" else 48),
            )
        basics.add_widget(Copy(text="Категория", size=11, bold=True, color=MUTED, height=22))
        self.category = Select(
            text=CATEGORIES[values.get("category", "community")],
            values=tuple(v for k, v in CATEGORIES.items() if k != "all"),
        )
        basics.add_widget(self.category)
        column.add_widget(basics)
        timing = form_card()
        timing.add_widget(section("02  Время и гости"))
        date = (
            datetime.fromisoformat(event["starts_at"]).astimezone(MSK)
            if event
            else datetime.now(MSK) + timedelta(days=1)
        )
        self.fields["date"] = labeled_field(
            timing,
            "Дата и время · Москва (UTC+3)",
            "ГГГГ-ММ-ДД ЧЧ:ММ",
            text=date.strftime("%Y-%m-%d %H:%M"),
        )
        self.fields["capacity"] = labeled_field(
            timing,
            "Количество мест",
            "30",
            text=str(values.get("capacity", 30)),
            input_filter="int",
        )
        column.add_widget(timing)
        self.coords = (values.get("latitude", MOSCOW[0]), values.get("longitude", MOSCOW[1]))
        column.add_widget(section("03  Точка на карте", "Нажмите на карту, чтобы выбрать место."))
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
        self.header("Добро пожаловать")
        scroll, column = scroll_column(16)
        self.layout.add_widget(scroll)
        column.add_widget(
            Hero(
                "Москва ближе,\nчем кажется.",
                "Встречайте своих людей. Открывайте новые места.",
                eyebrow="СЕГОДНЯ ИДЁМ / МОСКВА",
                height=204,
                category="culture",
            )
        )
        card = form_card()
        column.add_widget(card)
        card.add_widget(
            section(
                "Регистрация" if mode == "register" else "Вход в аккаунт",
                "Ваш следующий хороший вечер начинается здесь.",
            )
        )
        self.fields = {}
        if mode == "register":
            self.fields["name"] = labeled_field(card, "Как вас зовут?", "Ваше имя")
        self.fields["email"] = labeled_field(card, "Электронная почта", "you@example.com")
        self.fields["password"] = labeled_field(card, "Пароль", "Введите пароль", password=True)
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
        enter(card, offset=0)

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
        column.add_widget(
            Hero(
                "Письмо уже\nна пути.",
                "Остался один шаг до новых встреч.",
                eyebrow="БЕЗОПАСНЫЙ ВХОД",
                category="education",
                height=208,
            )
        )
        card = form_card(16)
        card.add_widget(section("Проверьте почту"))
        card.add_widget(
            Paragraph(
                text="Введите шестизначный код подтверждения. Он действует 10 минут.", color=MUTED
            )
        )
        self.code = Field("000000", input_filter="int", font_size=dp(28), height=dp(64))
        self.code.bind(on_text_validate=lambda *_: self.submit())
        card.add_widget(self.code)
        card.add_widget(Action("Войти", self.submit))
        card.add_widget(
            Action(
                "Получить новый код · Вернуться к входу",
                lambda: self.app.go_auth(),
                secondary=True,
                font_size=dp(11),
            )
        )
        column.add_widget(card)

    def submit(self):
        self.app.run_api(
            lambda: self.app.api.verify(self.challenge, self.code.text.strip()),
            lambda _: self.app.go_home(),
        )


class ProfileScreen(BaseScreen):
    def build(self):
        self.reset()
        self.header("Профиль", back=False)
        scroll, column = scroll_column()
        self.layout.add_widget(scroll)
        user = self.app.api.user
        if user:
            card = form_card(14)
            identity = BoxLayout(size_hint_y=None, height=dp(66), spacing=dp(14))
            initials = "".join(word[0] for word in user["name"].split()[:2]).upper()
            identity.add_widget(Avatar(initials, size=62))
            info = BoxLayout(orientation="vertical")
            info.add_widget(Copy(text=user["name"], size=21, bold=True, height=34, shorten=True))
            info.add_widget(Copy(text=user["email"], size=11, color=MUTED, height=26, shorten=True))
            identity.add_widget(info)
            card.add_widget(identity)
            card.add_widget(Badge(ROLES[user["role"]], category="sport"))
            column.add_widget(card)
            column.add_widget(
                Hero(
                    "Город ваш.",
                    "Собирайте впечатления, а не планы на потом.",
                    height=130,
                    compact=True,
                )
            )
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
            column.add_widget(
                Hero(
                    "Ваш город.\nВаши люди.",
                    "Войдите, чтобы сохранять встречи и создавать свои.",
                    eyebrow="ВАШ МАЛЕНЬКИЙ БОЛЬШОЙ ГОРОД",
                    height=214,
                    category="culture",
                )
            )
            column.add_widget(Action("Войти или зарегистрироваться", self.app.go_auth))
        connection = form_card()
        connection.add_widget(section("Подключение", "Адрес сервера для этого устройства."))
        self.server = Field("https://api.example.com", text=self.app.api.base_url)
        connection.add_widget(self.server)
        connection.add_widget(Action("Сохранить адрес API", self.set_server, secondary=True))
        column.add_widget(connection)
        column.add_widget(
            Paragraph(
                text="Сегодня идём · 1.1\nМероприятия, люди и любимый город.", size=11, color=MUTED
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
        column.add_widget(
            Hero(
                "Всё под контролем.",
                "Управление ролями · страница 1",
                eyebrow="КОМАНДА ГОРОДА",
                height=132,
                compact=True,
            )
        )
        for index, user in enumerate(data):
            panel = form_card(8)
            info = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(12))
            info.add_widget(
                Avatar("".join(word[0] for word in user["name"].split()[:2]).upper(), size=44)
            )
            labels = BoxLayout(orientation="vertical")
            labels.add_widget(Copy(text=user["name"], size=15, bold=True, height=25))
            labels.add_widget(Copy(text=user["email"], size=11, color=MUTED, height=23))
            info.add_widget(labels)
            panel.add_widget(info)
            row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
            spinner = Select(text=ROLES[user["role"]], values=tuple(ROLES.values()), height=dp(44))
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
                    height=dp(44),
                )
            )
            panel.add_widget(row)
            column.add_widget(panel)
            if index < 8:
                enter(panel, delay=index * 0.045, offset=0)
