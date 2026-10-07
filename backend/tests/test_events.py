def test_complete_crud_search_filters(client, account, payload):
    _, headers = account()
    r = client.post("/api/events", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    event = r.json()
    eid = event["id"]
    assert event["can_edit"] and event["author_name"] == "Тестовый пользователь"
    assert client.get(f"/api/events/{eid}").json()["title"] == payload["title"]
    found = client.get("/api/events", params={"search": "пикник", "category": "community"}).json()
    assert found["total"] == 1
    assert client.get("/api/events", params={"category": "music"}).json()["total"] == 0
    assert client.get("/api/events", params={"search": "%"}).json()["total"] == 0
    r = client.patch(f"/api/events/{eid}", json={"title": "Вечер у пруда"}, headers=headers)
    assert r.status_code == 200 and r.json()["title"] == "Вечер у пруда"
    assert client.delete(f"/api/events/{eid}", headers=headers).status_code == 204
    assert client.get(f"/api/events/{eid}").status_code == 404
    assert client.get("/api/events").json()["total"] == 0


def test_permission_model(client, account, payload, app):
    author, ha = account()
    attendee, ht = account("attendee@example.com", "attendee")
    other, ho = account("other@example.com")
    eid = client.post("/api/events", json=payload, headers=ha).json()["id"]
    assert client.post("/api/events", json=payload).status_code == 401
    assert client.post("/api/events", json=payload, headers=ht).status_code == 403
    assert (
        client.patch(f"/api/events/{eid}", json={"title": "Чужая запись"}, headers=ho).status_code
        == 403
    )
    assert client.delete(f"/api/events/{eid}", headers=ht).status_code == 403
    from app.models import User

    with app.state.db.sessions() as db:
        db.get(User, other["user"]["id"]).role = "moderator"
        db.commit()
    assert (
        client.patch(
            f"/api/events/{eid}", json={"title": "Модерация события"}, headers=ho
        ).status_code
        == 200
    )
    assert client.get("/api/admin/users", headers=ho).status_code == 403


def test_participation_capacity_and_cascade(client, account, payload):
    _, author = account()
    _, u1 = account("a@example.com", "attendee")
    _, u2 = account("b@example.com", "attendee")
    _, u3 = account("c@example.com", "attendee")
    eid = client.post("/api/events", json=payload, headers=author).json()["id"]
    assert client.post(f"/api/events/{eid}/join", headers=u1).status_code == 201
    assert client.post(f"/api/events/{eid}/join", headers=u1).status_code == 409
    assert client.post(f"/api/events/{eid}/join", headers=u2).status_code == 201
    assert client.post(f"/api/events/{eid}/join", headers=u3).status_code == 409
    assert (
        client.patch(f"/api/events/{eid}", json={"capacity": 1}, headers=author).status_code == 409
    )
    assert client.get("/api/events", params={"joined": True}, headers=u1).json()["total"] == 1
    assert client.get(f"/api/events/{eid}", headers=u1).json()["joined"]
    assert client.delete(f"/api/events/{eid}/join", headers=u1).status_code == 204
    assert client.delete(f"/api/events/{eid}/join", headers=u1).status_code == 404
    assert client.get(f"/api/events/{eid}").json()["attendees"] == 1
    assert client.delete(f"/api/events/{eid}", headers=author).status_code == 204
    assert client.get("/api/events", params={"joined": True}, headers=u2).json()["total"] == 0


def test_input_errors_and_future_date(client, account, payload):
    _, headers = account()
    assert client.post("/api/events", json={}, headers=headers).status_code == 400
    assert (
        client.post("/api/events", json={**payload, "latitude": 91}, headers=headers).status_code
        == 400
    )
    assert (
        client.post(
            "/api/events", json={**payload, "starts_at": "2020-01-01T12:00:00Z"}, headers=headers
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/events", json={**payload, "starts_at": "2030-01-01T12:00:00"}, headers=headers
        ).status_code
        == 400
    )
    eid = client.post("/api/events", json=payload, headers=headers).json()["id"]
    assert (
        client.patch(f"/api/events/{eid}", json={"title": None}, headers=headers).status_code == 400
    )
    assert client.patch(f"/api/events/{eid}", json={}, headers=headers).status_code == 400
    assert (
        client.patch(f"/api/events/{eid}", json={"title": "    "}, headers=headers).status_code
        == 400
    )
    assert client.get("/api/events", params={"page": 0}).status_code == 400
    assert client.get("/api/events", params={"after": "2030-01-01T00:00:00"}).status_code == 400
    assert client.get("/api/events", params={"joined": True}).status_code == 401


def test_concurrent_capacity_optimistic_lock(account, client, payload, app):
    _, headers = account()
    eid = client.post("/api/events", json=payload, headers=headers).json()["id"]
    from app.models import Event
    from sqlalchemy.orm.exc import StaleDataError
    import pytest

    with app.state.db.sessions() as first, app.state.db.sessions() as second:
        a = first.get(Event, eid)
        b = second.get(Event, eid)
        a.attendees += 1
        b.attendees += 1
        first.commit()
        with pytest.raises(StaleDataError):
            second.commit()
        second.rollback()
