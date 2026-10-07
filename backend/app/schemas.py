from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

Role = Literal["attendee", "organizer", "moderator", "admin"]
Category = Literal["culture", "music", "sport", "community", "education"]


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class Register(Schema):
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    role: Literal["attendee", "organizer"] = "attendee"

    @field_validator("name")
    @classmethod
    def name_valid(cls, v):
        if len(v.strip()) < 2:
            raise ValueError("Укажите имя")
        return v.strip()

    @field_validator("password")
    @classmethod
    def strong_password(cls, v):
        if not (
            any(c.islower() for c in v)
            and any(c.isupper() for c in v)
            and any(c.isdigit() for c in v)
        ):
            raise ValueError("Пароль: минимум 10 символов, строчная и заглавная буквы, цифра")
        return v


class Login(Schema):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ChallengeOut(Schema):
    challenge_id: str
    expires_in: int = 600
    delivery: Literal["email", "development_file"] = "email"


class Verify(Schema):
    challenge_id: str = Field(min_length=20, max_length=64)
    code: str = Field(pattern=r"^\d{6}$")


class UserOut(Schema):
    id: int
    name: str
    email: str
    role: Role
    active: bool


class Tokens(Schema):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class Refresh(Schema):
    refresh_token: str = Field(min_length=32, max_length=200)


class EventInput(Schema):
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=10, max_length=5000)
    category: Category
    starts_at: datetime
    address: str = Field(min_length=3, max_length=240)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    capacity: int = Field(ge=1, le=100000)

    @field_validator("title", "description", "address")
    @classmethod
    def trim(cls, v):
        if not v.strip():
            raise ValueError("Поле не может быть пустым")
        return v.strip()

    @field_validator("starts_at")
    @classmethod
    def utc_date(cls, v):
        if v.tzinfo is None:
            raise ValueError("Укажите часовой пояс даты")
        return v.astimezone(timezone.utc)


class EventPatch(Schema):
    title: str | None = Field(default=None, min_length=3, max_length=120)
    description: str | None = Field(default=None, min_length=10, max_length=5000)
    category: Category | None = None
    starts_at: datetime | None = None
    address: str | None = Field(default=None, min_length=3, max_length=240)
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    capacity: int | None = Field(default=None, ge=1, le=100000)

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_fields_set or any(
            getattr(self, key) is None for key in self.model_fields_set
        ):
            raise ValueError("Изменения должны содержать непустые поля")
        return self


class EventOut(Schema):
    id: int
    author_id: int
    author_name: str
    title: str
    description: str
    category: Category
    starts_at: datetime
    address: str
    latitude: float
    longitude: float
    capacity: int
    attendees: int
    joined: bool
    can_edit: bool


class EventPage(Schema):
    items: list[EventOut]
    total: int
    page: int
    page_size: int


class RoleUpdate(Schema):
    role: Role


class ErrorResponse(BaseModel):
    error: str
    request_id: str | None = None
    details: list[dict] | None = None
