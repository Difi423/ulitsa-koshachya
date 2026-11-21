"""Проверка данных повторяется на сервере: запрос можно сделать без браузерной формы."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import re

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator
from typing import Annotated, Literal

MOSCOW = timezone(timedelta(hours=3))
FRONTEND = Path(__file__).resolve().parents[1] / 'frontend'


class InputModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


def valid_name(value):
    if not 2 <= len(value) <= 60 or not value[0].isalpha() or not all(char.isalpha() or char in " '-’" for char in value):
        raise ValueError('Введите имя длиной 2–60 символов: буквы, пробелы, дефис или апостроф.')
    return value


def valid_login(value):
    if not re.fullmatch(r'[a-zA-Zа-яА-ЯёЁ0-9][a-zA-Zа-яА-ЯёЁ0-9_.-]{0,39}', value):
        raise ValueError('Введите логин: 1–40 букв, цифр, точек, дефисов или подчёркиваний; начните с буквы или цифры.')
    return value.lower()


class Login(InputModel):
    login: str = Field(min_length=1, max_length=40)
    password: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(min_length=1, max_length=128)

    @field_validator('login')
    @classmethod
    def check_login(cls, value):
        return valid_login(value)

class AdminAccount(Login):
    name: str = Field(max_length=60)

    @field_validator('name')
    @classmethod
    def check_name(cls, value):
        return valid_name(value)


class Application(InputModel):
    pet_id: int = Field(gt=0, strict=True)
    visitor_name: str = Field(max_length=60)
    phone: str = Field(max_length=40)
    visit_date: str
    visit_time: Literal['12-14', '14-16', '16-18']
    comment: str = Field(default='', max_length=1500)
    confirmed: Literal[True]

    @field_validator('confirmed', mode='before')
    @classmethod
    def check_confirmed(cls, value):
        if value is not True:
            raise ValueError('Подтвердите согласование времени с куратором.')
        return value

    @field_validator('visitor_name')
    @classmethod
    def check_name(cls, value):
        return valid_name(value)

    @field_validator('phone')
    @classmethod
    def check_phone(cls, value):
        digits = re.sub(r'\D', '', value)
        if not re.fullmatch(r'[+\d\s()-]+', value) or not (len(digits) == 10 or len(digits) == 11 and digits[0] in '78'):
            raise ValueError('Введите 10 цифр номера или 11 цифр с кодом 7 либо 8.')
        return '+7' + (digits if len(digits) == 10 else digits[1:])

    @field_validator('visit_date')
    @classmethod
    def check_date(cls, value):
        try:
            day = date.fromisoformat(value)
            if day.isoformat() != value:
                raise ValueError()
        except ValueError:
            raise ValueError('Выберите корректную дату визита.')
        if day < datetime.now(MOSCOW).date():
            raise ValueError('Дата визита не может быть в прошлом.')
        if day.weekday() == 0:
            raise ValueError('По понедельникам приют закрыт.')
        return value


class Message(InputModel):
    name: str = Field(max_length=60)
    topic: Literal['adoption', 'volunteer', 'help', 'question']
    message: str = Field(min_length=10, max_length=2000)

    @field_validator('name')
    @classmethod
    def check_name(cls, value):
        return valid_name(value)


def valid_image(value):
    static = re.fullmatch(r'images/(?:pets/)?[a-z0-9-]+\.(?:jpg|png|webp)', value)
    media = re.fullmatch(r'media/[a-f0-9]{32}\.webp', value)
    if not media and (not static or not (FRONTEND / value).is_file()):
        raise ValueError('Выберите существующее фото или загрузите изображение.')
    return value


class PetPhoto(InputModel):
    image: str = Field(max_length=150)
    alt: str = Field(default='', max_length=200)
    _image = field_validator('image')(valid_image)


class Pet(InputModel):
    slug: str = Field(pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$', min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=60)
    ageMonths: int = Field(ge=0, le=360, strict=True)
    sex: Literal['male', 'female']
    temperament: list[Literal['calm', 'social', 'playful']] = Field(min_length=1, max_length=3)
    trait: str = Field(min_length=1, max_length=80)
    color: str = Field(min_length=1, max_length=80)
    short: str = Field(min_length=10, max_length=300)
    story: str = Field(min_length=10, max_length=3000)
    home: str = Field(min_length=10, max_length=2000)
    care: str = Field(min_length=10, max_length=2000)
    image: str = Field(max_length=150)
    alt: str = Field(min_length=5, max_length=200)
    featured: bool = False
    status: Literal['available', 'reserved', 'adopted', 'archived'] = 'available'
    photos: list[PetPhoto] | None = Field(default=None, min_length=1, max_length=12)
    adoptionStory: str = Field(default='', max_length=2000)
    adoptedAt: str = ''

    @field_validator('image')
    @classmethod
    def check_image(cls, value):
        return valid_image(value)

    @field_validator('adoptedAt')
    @classmethod
    def adoption_date(cls, value):
        if value:
            try:
                day = date.fromisoformat(value)
                if day.isoformat() != value or day > datetime.now(MOSCOW).date():
                    raise ValueError()
            except ValueError:
                raise ValueError('Укажите корректную дату пристройства, не в будущем.')
        return value

    @model_validator(mode='after')
    def gallery(self):
        if self.photos is not None:
            paths = [photo.image for photo in self.photos]
            if len(set(paths)) != len(paths) or self.image not in paths:
                raise ValueError('В галерее нужны разные фото, включая выбранную обложку.')
        return self


class ApplicationStatus(InputModel):
    status: Literal['new', 'confirmed', 'completed', 'cancelled']
    admin_note: str = Field(default='', max_length=1500)
    visit_date: str | None = None
    visit_time: Literal['12-14', '14-16', '16-18'] | None = None

    @field_validator('visit_date')
    @classmethod
    def check_visit_date(cls, value):
        return Application.check_date(value) if value is not None else None


class MessageStatus(InputModel):
    status: Literal['new', 'read', 'closed']
