"""Настройки релиза. Значения берутся из окружения, без паролей в исходниках."""
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
import os

ROOT = Path(__file__).resolve().parents[1]


def origin(value):
    """Нормализуем HTTP origin; путь, userinfo и параметры здесь недопустимы."""
    parts = urlsplit(value.strip())
    if (parts.scheme not in ('http', 'https') or not parts.hostname
            or parts.username is not None or parts.password is not None
            or parts.path not in ('', '/') or parts.query or parts.fragment):
        raise ValueError('Укажите адрес вида https://cats.example.org без пути и параметров.')
    host = parts.hostname.lower()
    if ':' in host:
        host = f'[{host}]'
    port = parts.port
    if port is not None and not 1 <= port <= 65535:
        raise ValueError('Недопустимый порт в адресе сайта.')
    suffix = f':{port}' if port and port != {'http': 80, 'https': 443}[parts.scheme] else ''
    return f'{parts.scheme}://{host}{suffix}'


def flag(value, default):
    if value is None or value == '':
        return default
    if value not in ('0', '1'):
        raise ValueError('Логическая настройка должна быть 0 или 1.')
    return value == '1'


@dataclass(frozen=True)
class Settings:
    database: Path
    environment: str = 'development'
    public_origin: str = ''
    secure_cookies: bool = False
    allowed_hosts: tuple = ('*',)
    api_docs: bool = True
    host: str = '127.0.0.1'
    port: int = 8000
    trusted_proxies: str = ''
    log_level: str = 'info'
    uploads: Path | None = None
    slot_capacity: int = 1

    @classmethod
    def from_env(cls, values=None):
        values = os.environ if values is None else values
        environment = values.get('SHELTER_ENV', 'development').strip().lower()
        if environment not in ('development', 'production'):
            raise ValueError('SHELTER_ENV: development или production.')
        production = environment == 'production'
        public = values.get('SHELTER_PUBLIC_ORIGIN', '').strip()
        public = origin(public) if public else ''
        secure = flag(values.get('SHELTER_SECURE_COOKIES'), production)
        if production and (not public.startswith('https://') or not secure):
            raise ValueError('Для production нужны SHELTER_PUBLIC_ORIGIN с HTTPS и Secure cookie.')
        hosts = tuple(host.strip().lower() for host in values.get('SHELTER_ALLOWED_HOSTS', '').split(',') if host.strip())
        if not hosts:
            hosts = (urlsplit(public).hostname, 'localhost', '127.0.0.1') if public else ('*',)
        if production and '*' in hosts:
            raise ValueError('В production перечислите домены вместо SHELTER_ALLOWED_HOSTS=*.')
        port = int(values.get('PORT') or values.get('SHELTER_PORT') or 8000)
        if not 1 <= port <= 65535:
            raise ValueError('Порт должен быть от 1 до 65535.')
        level = values.get('SHELTER_LOG_LEVEL', 'info').strip().lower()
        if level not in ('critical', 'error', 'warning', 'info', 'debug'):
            raise ValueError('Неизвестный SHELTER_LOG_LEVEL.')
        capacity = int(values.get('SHELTER_SLOT_CAPACITY') or 1)
        if not 1 <= capacity <= 8:
            raise ValueError('SHELTER_SLOT_CAPACITY: от 1 до 8 встреч в интервале.')
        return cls(
            database=Path(values.get('SHELTER_DB') or ROOT / 'data' / 'shelter.sqlite3'),
            environment=environment, public_origin=public, secure_cookies=secure,
            allowed_hosts=hosts, api_docs=flag(values.get('SHELTER_API_DOCS'), not production),
            host=values.get('SHELTER_HOST') or '127.0.0.1', port=port,
            trusted_proxies=values.get('SHELTER_TRUSTED_PROXIES', '').strip(), log_level=level,
            uploads=Path(values['SHELTER_UPLOADS_DIR']) if values.get('SHELTER_UPLOADS_DIR') else None,
            slot_capacity=capacity,
        )
