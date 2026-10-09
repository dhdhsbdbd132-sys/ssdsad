"""Persistent local test data. This adapter never connects to an API or sends mail."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import tempfile
from threading import RLock

from todaygo.api import ApiError


CATEGORIES = {"culture", "music", "sport", "community", "education"}
INPUT_FIELDS = {
    "title",
    "description",
    "category",
    "starts_at",
    "address",
    "latitude",
    "longitude",
    "capacity",
}
RECORD_FIELDS = INPUT_FIELDS | {"id", "author_id", "author_name", "attendees", "joined"}
DEMO_USER = {
    "id": 1,
    "name": "Тестовый организатор",
    "email": "demo@example.test",
    "role": "organizer",
    "active": True,
}
MAX_FILE_BYTES = 8 * 1024 * 1024


def _date(value):
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(parsed, datetime) or parsed.tzinfo is None:
            raise ValueError
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        raise ApiError("Укажите дату и часовой пояс в формате ISO 8601", 400) from None


def _integer(value, minimum=1, maximum=None):
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ApiError("Некорректное целое число", 400)
    return value


def _inputs(data, *, future=True):
    if not isinstance(data, dict) or set(data) != INPUT_FIELDS:
        raise ApiError("Заполните все поля мероприятия без лишних параметров", 400)
    result = deepcopy(data)
    for field, minimum, maximum in (
        ("title", 3, 120),
        ("description", 10, 5000),
        ("address", 3, 240),
    ):
        value = result[field]
        if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
            raise ApiError(f"Проверьте поле «{field}»: от {minimum} до {maximum} символов", 400)
        result[field] = value.strip()
    if not isinstance(result["category"], str) or result["category"] not in CATEGORIES:
        raise ApiError("Выберите категорию мероприятия", 400)
    for field, minimum, maximum in (("latitude", -90, 90), ("longitude", -180, 180)):
        value = result[field]
        if (
            type(value) not in (int, float)
            or not minimum <= value <= maximum
            or not math.isfinite(value)
        ):
            raise ApiError("Проверьте координаты места встречи", 400)
        result[field] = float(value)
    result["capacity"] = _integer(result["capacity"], maximum=100000)
    starts_at = _date(result["starts_at"])
    if future and starts_at <= datetime.now(timezone.utc):
        raise ApiError("Дата события должна быть в будущем", 400)
    result["starts_at"] = starts_at.isoformat()
    return result


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


class DemoClient:
    """An ApiClient-compatible, single-user demo stored separately from real data."""

    def __init__(self, data_path: Path):
        self.data_path = Path(data_path)
        self._lock = RLock()
        self._signed_in = True
        with self._lock:
            try:
                raw = self.data_path.read_bytes()
            except FileNotFoundError:
                self._store = self._seed()
                self._write(self._store)
            except OSError:
                raise ApiError("Не удалось прочитать локальные тестовые данные", 500) from None
            else:
                try:
                    if len(raw) > MAX_FILE_BYTES:
                        raise ValueError("File too large")
                    self._store = self._validate_store(
                        json.loads(raw.decode("utf-8"), object_pairs_hook=_json_object)
                    )
                except (ValueError, TypeError, KeyError, UnicodeError, ApiError):
                    raise ApiError(
                        "Файл тестовых данных повреждён. Он сохранён без изменений. "
                        "Переименуйте demo/events.json для создания нового демо.",
                        500,
                    ) from None

    @property
    def user(self):
        with self._lock:
            return deepcopy(DEMO_USER) if self._signed_in else None

    def login_demo(self):
        with self._lock:
            self._signed_in = True
            return self.user

    def clear_tokens(self):
        with self._lock:
            self._signed_in = False

    def logout(self):
        self.clear_tokens()

    def close(self):
        """No sockets or background workers are owned by this adapter."""

    def _require_user(self):
        if not self._signed_in:
            raise ApiError("Войдите в тестовый профиль", 401)

    @staticmethod
    def _seed():
        now = datetime.now(timezone.utc)
        places = (
            ("Прогулка по Парку Горького", "community", "Крымский Вал, 9", 55.7299, 37.6012),
            ("Музыкальный вечер на ВДНХ", "music", "Проспект Мира, 119", 55.8298, 37.6316),
            ("Утренняя пробежка в Лужниках", "sport", "Лужнецкая набережная, 24", 55.7157, 37.5537),
            ("Культурная встреча в Зарядье", "culture", "Улица Варварка, 6", 55.7515, 37.6288),
            (
                "Фотопрогулка на Патриарших",
                "education",
                "Большой Патриарший переулок",
                55.7637,
                37.5930,
            ),
            ("Пикник в Сокольниках", "community", "Сокольнический Вал, 1", 55.7946, 37.6783),
        )
        records = []
        for index, (title, category, address, lat, lon) in enumerate(places, 1):
            owned = index in (1, 4)
            records.append(
                {
                    "id": index,
                    "author_id": 1 if owned else 2,
                    "author_name": DEMO_USER["name"] if owned else "Команда Сегодня идём",
                    "title": title,
                    "description": (
                        "Тестовое событие для знакомства с приложением. "
                        "Посмотрите место на карте, присоединитесь к встрече или создайте свой план. "
                        "Данные и участие сохраняются только на вашем устройстве."
                    ),
                    "category": category,
                    "starts_at": (now + timedelta(days=index))
                    .replace(hour=15, minute=0, second=0, microsecond=0)
                    .isoformat(),
                    "address": address,
                    "latitude": lat,
                    "longitude": lon,
                    "capacity": 20 + index * 5,
                    "attendees": index + (1 if index == 2 else 0),
                    "joined": index == 2,
                }
            )
        return {"version": 1, "next_id": 7, "events": records}

    @staticmethod
    def _validate_store(store):
        if (
            not isinstance(store, dict)
            or set(store) != {"version", "next_id", "events"}
            or type(store["version"]) is not int
            or store["version"] != 1
            or not isinstance(store["events"], list)
        ):
            raise ValueError("Unknown format")
        next_id = _integer(store["next_id"])
        ids = set()
        for record in store["events"]:
            if not isinstance(record, dict) or set(record) != RECORD_FIELDS:
                raise ValueError("Invalid record")
            event_id = _integer(record["id"])
            _integer(record["author_id"])
            if event_id in ids or event_id >= next_id:
                raise ValueError("Invalid event identifier")
            ids.add(event_id)
            if (
                not isinstance(record["author_name"], str)
                or not 2 <= len(record["author_name"].strip()) <= 80
                or type(record["joined"]) is not bool
            ):
                raise ValueError("Invalid author or participation")
            validated = _inputs({key: record[key] for key in INPUT_FIELDS}, future=False)
            _integer(record["attendees"], minimum=0, maximum=record["capacity"])
            if record["joined"] and record["attendees"] == 0:
                raise ValueError("Invalid participation count")
            record.update(validated)
        return store

    def _write(self, store):
        temporary = None
        try:
            self.data_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            payload = json.dumps(store, ensure_ascii=False, allow_nan=False, indent=2)
            if len(payload.encode("utf-8")) > MAX_FILE_BYTES:
                raise ApiError("Лимит локальных тестовых данных превышен", 400)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.data_path.parent,
                prefix=".events-",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.data_path)
        except OSError:
            raise ApiError(
                "Не удалось сохранить тестовые данные. Изменения отменены; проверьте доступ к папке.",
                500,
            ) from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def _commit(self, store):
        self._write(store)
        self._store = store

    def _record(self, event_id, store=None):
        _integer(event_id)
        for record in (self._store if store is None else store)["events"]:
            if record["id"] == event_id:
                return record
        raise ApiError("Мероприятие не найдено", 404)

    def _output(self, record):
        result = deepcopy(record)
        result["joined"] = bool(self._signed_in and record["joined"])
        result["can_edit"] = bool(self._signed_in and record["author_id"] == DEMO_USER["id"])
        return result

    def events(self, **params):
        with self._lock:
            if set(params) - {
                "search",
                "category",
                "after",
                "before",
                "author_id",
                "joined",
                "page",
                "page_size",
            }:
                raise ApiError("Неизвестный фильтр мероприятий", 400)
            search = params.get("search", "")
            if not isinstance(search, str) or len(search) > 120:
                raise ApiError("Поиск должен содержать не более 120 символов", 400)
            category = params.get("category")
            if category is not None and (
                not isinstance(category, str) or category not in CATEGORIES
            ):
                raise ApiError("Неизвестная категория", 400)
            page = _integer(params.get("page", 1))
            page_size = _integer(params.get("page_size", 20), maximum=100)
            author_id = params.get("author_id")
            if author_id is not None:
                _integer(author_id)
            joined = params.get("joined", False)
            if type(joined) is not bool:
                raise ApiError("Некорректный фильтр участия", 400)
            if joined:
                self._require_user()
            after = _date(params["after"]) if params.get("after") is not None else None
            before = _date(params["before"]) if params.get("before") is not None else None
            if after and before and after > before:
                raise ApiError("Некорректный диапазон дат", 400)
            found = []
            for record in self._store["events"]:
                if (
                    search.casefold()
                    not in " ".join(
                        record[key] for key in ("title", "description", "address")
                    ).casefold()
                ):
                    continue
                starts_at = _date(record["starts_at"])
                if (
                    (category is not None and record["category"] != category)
                    or (after is not None and starts_at < after)
                    or (before is not None and starts_at > before)
                    or (author_id is not None and record["author_id"] != author_id)
                    or (joined and not record["joined"])
                ):
                    continue
                found.append(record)
            found.sort(key=lambda record: (_date(record["starts_at"]), record["id"]))
            start = (page - 1) * page_size
            return {
                "items": [self._output(record) for record in found[start : start + page_size]],
                "total": len(found),
                "page": page,
                "page_size": page_size,
            }

    def event(self, event_id):
        with self._lock:
            return self._output(self._record(event_id))

    def save_event(self, data, event_id=None):
        with self._lock:
            self._require_user()
            store = deepcopy(self._store)
            if event_id is None:
                record = _inputs(data)
                record.update(
                    id=store["next_id"],
                    author_id=DEMO_USER["id"],
                    author_name=DEMO_USER["name"],
                    attendees=0,
                    joined=False,
                )
                store["events"].append(record)
                store["next_id"] += 1
            else:
                record = self._record(event_id, store)
                self._require_owner(record, "редактирование")
                if not isinstance(data, dict) or not data or set(data) - INPUT_FIELDS:
                    raise ApiError("Укажите непустые изменения без лишних полей", 400)
                merged = {key: record[key] for key in INPUT_FIELDS}
                merged.update(data)
                validated = _inputs(merged)
                if validated["capacity"] < record["attendees"]:
                    raise ApiError("Вместимость меньше числа участников", 409)
                record.update(validated)
            self._commit(store)
            return self._output(record)

    @staticmethod
    def _require_owner(record, action):
        if record["author_id"] != DEMO_USER["id"]:
            raise ApiError(f"Нет прав на {action}", 403)

    def delete_event(self, event_id):
        with self._lock:
            self._require_user()
            store = deepcopy(self._store)
            record = self._record(event_id, store)
            self._require_owner(record, "удаление")
            store["events"].remove(record)
            self._commit(store)

    def join(self, event_id):
        with self._lock:
            self._require_user()
            store = deepcopy(self._store)
            record = self._record(event_id, store)
            if _date(record["starts_at"]) <= datetime.now(timezone.utc):
                raise ApiError("Мероприятие уже началось", 400)
            if record["joined"]:
                raise ApiError("Вы уже участвуете", 409)
            if record["attendees"] >= record["capacity"]:
                raise ApiError("Свободных мест нет", 409)
            record["joined"] = True
            record["attendees"] += 1
            self._commit(store)
            return self._output(record)

    def leave(self, event_id):
        with self._lock:
            self._require_user()
            store = deepcopy(self._store)
            record = self._record(event_id, store)
            if not record["joined"]:
                raise ApiError("Участие не найдено", 404)
            record["joined"] = False
            record["attendees"] -= 1
            self._commit(store)
