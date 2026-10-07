# API

Base path: `/api`. Для JSON-запросов `Content-Type: application/json`. Защищённые методы: `Authorization: Bearer <access_token>`. Полная машинная схема: `/openapi.json`, интерактивная документация: `/docs`.

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/health` | Проверка сервера и БД |
| POST | `/auth/register` | Регистрация; возвращает challenge |
| POST | `/auth/login` | Пароль; возвращает challenge |
| POST | `/auth/verify` | Почтовый код; возвращает access/refresh и пользователя |
| POST | `/auth/token` | OAuth2 form endpoint после получения challenge |
| POST | `/auth/refresh` | Одноразовая ротация refresh |
| POST | `/auth/logout` | Отзыв семейства сессии; 204 |
| GET | `/auth/me` | Текущий пользователь |
| GET | `/auth/oauth/start` | Начало Google OIDC / PKCE |
| GET | `/auth/oauth/callback` | Обмен кода провайдера; HTML-подтверждение |
| POST | `/auth/oauth/poll` | Одноразовое получение challenge мобильным клиентом |
| GET | `/events` | Список, поиск, фильтры, страницы |
| GET | `/events/{id}` | Запись |
| POST | `/events` | Создание; 201 |
| PATCH | `/events/{id}` | Частичное изменение |
| DELETE | `/events/{id}` | Удаление; 204 |
| POST | `/events/{id}/join` | Участие; 201 |
| DELETE | `/events/{id}/join` | Отмена участия; 204 |
| GET | `/admin/users` | Пользователи, страница `page` |
| PATCH | `/admin/users/{id}/role` | Назначение роли; отзыв сессий |
| GET | `/admin/audit` | Аудит, параметр `limit` |

## Пример мероприятия

```json
{
  "title": "Прогулка по Москве",
  "description": "Встречаемся у Манежной площади и исследуем центр города.",
  "category": "culture",
  "starts_at": "2027-05-20T18:00:00+03:00",
  "address": "Москва, Манежная площадь",
  "latitude": 55.754,
  "longitude": 37.614,
  "capacity": 20
}
```

Категории: `culture`, `music`, `sport`, `community`, `education`. PATCH принимает только изменённые поля; пустой объект и явные `null` запрещены. Дополнительные неизвестные поля запрещены Pydantic. Автор, счётчик участников и роли задаются сервером.

Ответ мероприятия дополнен `id`, `author_id`, `author_name`, `attendees`, `joined`, `can_edit`. Список: `{ "items": [...], "total": 6, "page": 1, "page_size": 20 }`.

Фильтры: `search`, `category`, `after`, `before`, `author_id`, `joined`, `page`, `page_size` (не более 100). `joined=true` требует входа. `after`/`before` — ISO 8601 с часовым поясом. В API доступны события любой даты; главный экран по умолчанию показывает будущие.

## Авторизация

`register`: `name`, `email`, `password`, `role` (только `attendee`/`organizer`). `login`: `email`, `password`. Оба возвращают `challenge_id`, `expires_in=600`, `delivery=email`. Затем `verify`: `challenge_id`, шестизначный `code`. Токены выдаются только после подтверждения.

`refresh` принимает `{ "refresh_token": "..." }`; старый токен после успешного запроса использовать нельзя. Выход отзывает текущую сессию, включая ранее выданные access-токены.

Для кнопки Swagger **Authorize** сначала вызовите `/auth/login`, затем в username укажите `challenge_id`, в password — почтовый код. OAuth2 `/auth/token` использует form-urlencoded по стандарту; остальные основные запросы используют JSON. Это совместимость OAuth2/OpenAPI, а не способ обхода второго фактора.

## Ошибки

Единый JSON-ответ:

```json
{"error":"Мероприятие не найдено","request_id":"идентификатор"}
```

Ошибки валидации содержат `details` со списком полей и сообщений, без исходных паролей/кодов.

| Код | Значение |
|---|---|
| 400 | Невалидные данные, прошлое событие, некорректная дата |
| 401 | Нет/истёк токен, неверный пароль/код, повторный refresh |
| 403 | Нет прав |
| 404 | Нет события, пользователя или участия |
| 409 | Дубликат, заполненное событие, конкурентное изменение |
| 413 | Тело больше 64 KiB |
| 429 | Лимит запросов; `Retry-After: 60` |
| 500 | Внутренняя ошибка без раскрытия деталей |
| 502 | Недоступен OAuth-провайдер |
| 503 | Почта/OAuth не настроены или почта недоступна |

Валидация FastAPI нормализована с 422 на 400; схема OpenAPI соответствует фактическим ответам.
