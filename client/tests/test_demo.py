"""Offline demo uses the production client's contract without opening any connection."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json

import pytest
import requests

from todaygo.api import ApiError
from todaygo.demo import DemoClient


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("The local demo attempted to use the network")

    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(requests, "Session", forbidden)


@pytest.fixture
def client(tmp_path):
    return DemoClient(tmp_path / "private" / "demo" / "events.json")


def event_input(**changes):
    data = {
        "title": "Моя встреча в Москве",
        "description": "Тестируем создание и сохранение мероприятия на устройстве.",
        "category": "education",
        "starts_at": (datetime.now(timezone.utc) + timedelta(days=10)).isoformat(),
        "address": "Улица Тверская, 1",
        "latitude": 55.757,
        "longitude": 37.615,
        "capacity": 12,
    }
    data.update(changes)
    return data


def assert_status(status, operation):
    with pytest.raises(ApiError) as caught:
        operation()
    assert caught.value.status == status


def test_seed_and_return_contract_are_detached(client):
    assert client.user == {
        "id": 1,
        "name": "Тестовый организатор",
        "email": "demo@example.test",
        "role": "organizer",
        "active": True,
    }
    page = client.events()
    assert set(page) == {"items", "total", "page", "page_size"}
    assert page["total"] == 6
    assert len(page["items"]) == 6
    assert {event["category"] for event in page["items"]} == {
        "culture",
        "music",
        "sport",
        "community",
        "education",
    }
    expected = set(event_input()) | {
        "id",
        "author_id",
        "author_name",
        "attendees",
        "joined",
        "can_edit",
    }
    for event in page["items"]:
        assert set(event) == expected
        assert datetime.fromisoformat(event["starts_at"]) > datetime.now(timezone.utc)
        assert 55.6 < event["latitude"] < 55.9 and 37.4 < event["longitude"] < 37.8
        assert event["can_edit"] == (event["author_id"] == 1)
    page["items"][0]["title"] = "External mutation"
    assert client.event(1)["title"] != "External mutation"
    user = client.user
    user["role"] = "admin"
    assert client.user["role"] == "organizer"


def test_crud_and_participation_survive_reopen(client):
    created = client.save_event(event_input())
    assert created["id"] == 7 and created["can_edit"] and not created["joined"]
    updated = client.save_event({"title": "Изменённый план", "capacity": 15}, created["id"])
    assert updated["title"] == "Изменённый план"
    joined = client.join(3)
    assert joined["joined"] and joined["attendees"] == 4
    reopened = DemoClient(client.data_path)
    assert reopened.event(created["id"]) == updated
    assert reopened.event(3) == joined
    assert reopened.leave(3) is None
    assert not DemoClient(client.data_path).event(3)["joined"]
    assert reopened.delete_event(created["id"]) is None
    fresh = DemoClient(client.data_path)
    assert_status(404, lambda: fresh.event(created["id"]))
    assert fresh.save_event(event_input())["id"] == 8


def test_search_literal_category_dates_pagination_and_ownership(client):
    assert client.events(search="ЛУЖНЕЦКАЯ")["items"][0]["id"] == 3
    assert client.events(search="тестовое СОБЫТИЕ")["total"] == 6
    assert client.events(search="%_")["total"] == 0
    assert [event["id"] for event in client.events(category="community")["items"]] == [1, 6]
    first = client.events(page=1, page_size=2)
    second = client.events(page=2, page_size=2)
    assert first["total"] == second["total"] == 6
    assert [event["id"] for event in first["items"]] == [1, 2]
    assert [event["id"] for event in second["items"]] == [3, 4]
    assert client.events(page=9, page_size=2)["items"] == []
    after, before = client.event(2)["starts_at"], client.event(4)["starts_at"]
    assert [event["id"] for event in client.events(after=after, before=before)["items"]] == [
        2,
        3,
        4,
    ]
    msk = datetime.fromisoformat(after).astimezone(timezone(timedelta(hours=3))).isoformat()
    assert client.events(after=msk, before=msk)["total"] == 1
    assert [event["id"] for event in client.events(author_id=1)["items"]] == [1, 4]
    assert [event["id"] for event in client.events(joined=True)["items"]] == [2]


def test_duplicate_full_capacity_and_foreign_author_rejected_without_changes(client):
    original = client.data_path.read_bytes()
    assert_status(409, lambda: client.join(2))
    assert_status(404, lambda: client.leave(1))
    assert_status(403, lambda: client.save_event({"title": "Чужой план"}, 3))
    assert_status(403, lambda: client.delete_event(3))
    assert_status(409, lambda: client.save_event({"capacity": 1}, 4))
    assert original == client.data_path.read_bytes()
    own = client.save_event(event_input(capacity=1))
    client.join(own["id"])
    assert_status(409, lambda: client.join(own["id"]))
    store = json.loads(client.data_path.read_text(encoding="utf-8"))
    foreign = next(event for event in store["events"] if event["id"] == 3)
    foreign["attendees"] = foreign["capacity"]
    client.data_path.write_text(json.dumps(store), encoding="utf-8")
    full = DemoClient(client.data_path)
    full_before = full.data_path.read_bytes()
    assert_status(409, lambda: full.join(3))
    assert full.data_path.read_bytes() == full_before


def test_logout_is_local_and_fixed_demo_login_restores_participation(client):
    assert client.logout() is None
    assert client.user is None
    assert not client.event(2)["joined"] and not client.event(1)["can_edit"]
    assert client.events()["total"] == 6
    for operation in (
        lambda: client.save_event(event_input()),
        lambda: client.delete_event(1),
        lambda: client.join(3),
        lambda: client.leave(2),
        lambda: client.events(joined=True),
    ):
        assert_status(401, operation)
    user = client.login_demo()
    assert user == client.user
    assert client.event(2)["joined"] and client.event(1)["can_edit"]
    assert client.clear_tokens() is None and client.user is None
    client.close()
    assert client.login_demo()["role"] == "organizer"
    persisted = client.data_path.read_text(encoding="utf-8")
    assert "password" not in persisted and "token" not in persisted and "@" not in persisted


@pytest.mark.parametrize(
    "change",
    [
        {"title": " "},
        {"description": "short"},
        {"address": "x"},
        {"category": "invalid"},
        {"category": []},
        {"capacity": 0},
        {"capacity": True},
        {"capacity": 100001},
        {"latitude": float("nan")},
        {"longitude": float("inf")},
        {"latitude": 91},
        {"longitude": -181},
        {"latitude": "55.75"},
        {"latitude": 10**1000},
        {"starts_at": "2035-01-01T12:00:00"},
        {"starts_at": "2020-01-01T12:00:00+03:00"},
        {"starts_at": None},
    ],
)
def test_validation_rejects_bad_inputs_without_writes(client, change):
    before = client.data_path.read_bytes()
    assert_status(400, lambda: client.save_event(event_input(**change)))
    assert_status(400, lambda: client.save_event(change, 1))
    assert client.data_path.read_bytes() == before


@pytest.mark.parametrize(
    "filters",
    [
        {"category": "invalid"},
        {"search": "x" * 121},
        {"page": 0},
        {"page": True},
        {"page_size": 101},
        {"author_id": 0},
        {"joined": "false"},
        {"unsupported": True},
        {"after": "2035-01-01T12:00:00"},
        {"after": "2035-01-02T12:00:00Z", "before": "2035-01-01T12:00:00Z"},
    ],
)
def test_invalid_filters_have_api_errors(client, filters):
    assert_status(400, lambda: client.events(**filters))


def test_invalid_patches_missing_ids_and_extra_creation_fields(client):
    for patch in ({}, {"title": None}, {"author_id": 2}, {"capacity": None}):
        assert_status(400, lambda patch=patch: client.save_event(patch, 1))
    bad = event_input(secret="not accepted")
    assert_status(400, lambda: client.save_event(bad))
    del bad["secret"]
    del bad["title"]
    assert_status(400, lambda: client.save_event(bad))
    for operation in (
        lambda: client.event(999),
        lambda: client.delete_event(999),
        lambda: client.save_event({"title": "Новый план"}, 999),
        lambda: client.join(999),
        lambda: client.leave(999),
    ):
        assert_status(404, operation)


def test_atomic_replace_failure_does_not_change_memory_or_file(client, monkeypatch):
    original_file = client.data_path.read_bytes()
    original_page = client.events()

    def fail_replace(*args):
        raise PermissionError("simulated device write failure")

    monkeypatch.setattr("todaygo.demo.os.replace", fail_replace)
    for operation in (
        lambda: client.save_event(event_input()),
        lambda: client.save_event({"title": "Правка"}, 1),
        lambda: client.delete_event(1),
        lambda: client.join(3),
        lambda: client.leave(2),
    ):
        assert_status(500, operation)
        assert client.events() == original_page
        assert client.data_path.read_bytes() == original_file
        assert not list(client.data_path.parent.glob(".events-*.tmp"))
    monkeypatch.undo()
    assert client.save_event(event_input())["id"] == 7


@pytest.mark.parametrize(
    "corruption",
    [
        b"not JSON",
        b"\xff",
        b"{}",
        b'{"version":1,"version":1,"next_id":7,"events":[]}',
        b'{"version":2,"next_id":7,"events":[]}',
    ],
)
def test_corrupt_file_is_preserved(tmp_path, corruption):
    path = tmp_path / "demo" / "events.json"
    path.parent.mkdir()
    path.write_bytes(corruption)
    assert_status(500, lambda: DemoClient(path))
    assert path.read_bytes() == corruption


@pytest.mark.parametrize("damage", ["duplicate", "attendees", "joined", "coordinate", "next_id"])
def test_semantically_invalid_persisted_records_are_preserved(client, damage):
    store = json.loads(client.data_path.read_text(encoding="utf-8"))
    if damage == "duplicate":
        store["events"].append(store["events"][0].copy())
    elif damage == "attendees":
        store["events"][0]["attendees"] = -1
    elif damage == "joined":
        store["events"][0]["joined"] = "false"
    elif damage == "coordinate":
        store["events"][0]["latitude"] = float("nan")
    else:
        store["next_id"] = 1
    client.data_path.write_text(json.dumps(store), encoding="utf-8")
    corrupted = client.data_path.read_bytes()
    assert_status(500, lambda: DemoClient(client.data_path))
    assert client.data_path.read_bytes() == corrupted


def test_old_persisted_event_can_be_read_but_not_joined_or_edited(client):
    store = json.loads(client.data_path.read_text(encoding="utf-8"))
    store["events"][0]["starts_at"] = "2020-01-01T12:00:00+00:00"
    client.data_path.write_text(json.dumps(store), encoding="utf-8")
    old = DemoClient(client.data_path)
    assert old.event(1)["starts_at"].startswith("2020")
    assert_status(400, lambda: old.join(1))
    assert_status(400, lambda: old.save_event({"title": "Правка"}, 1))
    assert old.delete_event(1) is None


def test_concurrent_workers_keep_unique_ids_and_all_changes(client):
    with ThreadPoolExecutor(max_workers=6) as pool:
        created = list(
            pool.map(lambda index: client.save_event(event_input(title=f"План {index}")), range(12))
        )
    assert sorted(event["id"] for event in created) == list(range(7, 19))
    reopened = DemoClient(client.data_path)
    assert reopened.events()["total"] == 18
    assert {event["title"] for event in reopened.events()["items"] if event["id"] > 6} == {
        f"План {index}" for index in range(12)
    }
