import json
from datetime import datetime, timedelta, timezone
import pytest
from todaygo.api import ApiClient, ApiError


def test_real_server_crud_auth_participation(api_server):
    url, mail = api_server
    api = ApiClient(url)
    challenge = api.register(
        {
            "name": "Клиент API",
            "email": "client@example.com",
            "password": "ClientPassword42",
            "role": "organizer",
        }
    )
    code = json.loads((mail / f"{challenge['challenge_id']}.json").read_text())["code"]
    api.verify(challenge["challenge_id"], code)
    data = {
        "title": "Прогулка по Москве",
        "description": "Собираемся у Кремля и идём гулять по центру.",
        "category": "culture",
        "starts_at": (datetime.now(timezone.utc) + timedelta(days=4)).isoformat(),
        "address": "Манежная площадь",
        "latitude": 55.754,
        "longitude": 37.614,
        "capacity": 20,
    }
    event = api.save_event(data)
    assert api.events(search="Прогулка")["total"] == 1
    assert api.event(event["id"])["can_edit"]
    assert api.join(event["id"])["joined"]
    api.leave(event["id"])
    assert not api.event(event["id"])["joined"]
    assert api.save_event({"title": "Новая прогулка"}, event["id"])["title"] == "Новая прогулка"
    api.access = "expired-access-token"
    # A real 401 triggers refresh rotation and repeats the original operation.
    assert api.event(event["id"])["title"] == "Новая прогулка"
    api.delete_event(event["id"])
    with pytest.raises(ApiError) as error:
        api.event(event["id"])
    assert error.value.status == 404
    api.logout()
    assert api.access is None and api.refresh is None


@pytest.mark.parametrize(
    "url",
    [
        "http://remote.example.com",
        "https://user:pass@example.com",
        "https://example.com/path",
        "file:///etc/passwd",
    ],
)
def test_rejects_unsafe_server_addresses(url):
    with pytest.raises(ApiError):
        ApiClient(url)
