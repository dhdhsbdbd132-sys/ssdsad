"""The sole data gateway. Tokens stay in memory, never on disk or in logs."""

from urllib.parse import urlsplit
import requests


class ApiError(Exception):
    def __init__(self, message, status=0):
        super().__init__(message)
        self.status = status


class ApiClient:
    def __init__(self, base_url="http://127.0.0.1:8000"):
        self.base_url = self.validate_url(base_url)
        self.session = requests.Session()
        self.access = self.refresh = None
        self.user = None

    @staticmethod
    def validate_url(url):
        url = url.strip().rstrip("/")
        p = urlsplit(url)
        if not p.hostname or p.username or p.password or p.query or p.fragment or p.path:
            raise ApiError("Укажите адрес сервера без пути, пароля и параметров")
        if p.scheme != "https" and not (
            p.scheme == "http" and p.hostname in {"localhost", "127.0.0.1", "10.0.2.2"}
        ):
            raise ApiError("Для удалённого сервера требуется HTTPS")
        return url

    def request(self, method, path, body=None, params=None, retry=True):
        headers = {"Authorization": f"Bearer {self.access}"} if self.access else {}
        try:
            response = self.session.request(
                method,
                self.base_url + "/api" + path,
                json=body,
                params=params,
                headers=headers,
                timeout=(5, 15),
            )
        except requests.RequestException:
            raise ApiError("Нет связи с сервером. Проверьте интернет и адрес API") from None
        if (
            response.status_code == 401
            and self.refresh
            and retry
            and (not path.startswith("/auth/") or path in {"/auth/me", "/auth/logout"})
        ):
            try:
                self.set_tokens(
                    self.request(
                        "POST", "/auth/refresh", {"refresh_token": self.refresh}, retry=False
                    )
                )
            except ApiError:
                self.clear_tokens()
                raise ApiError("Сессия истекла. Войдите снова", 401) from None
            return self.request(method, path, body, params, retry=False)
        if response.status_code >= 400:
            try:
                data = response.json()
                message = data.get("error", "Ошибка запроса")
                if data.get("details"):
                    message += "\n" + "\n".join(d["message"] for d in data["details"][:3])
            except ValueError:
                message = "Сервер временно недоступен"
            raise ApiError(message, response.status_code)
        return response.json() if response.content else None

    def set_tokens(self, data):
        self.access, self.refresh, self.user = (
            data["access_token"],
            data["refresh_token"],
            data["user"],
        )
        return data

    def clear_tokens(self):
        self.access = self.refresh = self.user = None

    def register(self, data):
        return self.request("POST", "/auth/register", data)

    def login(self, email, password):
        return self.request("POST", "/auth/login", {"email": email, "password": password})

    def verify(self, challenge, code):
        return self.set_tokens(
            self.request("POST", "/auth/verify", {"challenge_id": challenge, "code": code})
        )

    def logout(self):
        if self.access:
            self.request("POST", "/auth/logout")
        self.clear_tokens()

    def events(self, **params):
        return self.request("GET", "/events", params=params)

    def event(self, event_id):
        return self.request("GET", f"/events/{event_id}")

    def save_event(self, data, event_id=None):
        return self.request(
            "PATCH" if event_id else "POST", f"/events/{event_id}" if event_id else "/events", data
        )

    def delete_event(self, event_id):
        return self.request("DELETE", f"/events/{event_id}")

    def join(self, event_id):
        return self.request("POST", f"/events/{event_id}/join")

    def leave(self, event_id):
        return self.request("DELETE", f"/events/{event_id}/join")
