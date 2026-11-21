# Улица Кошачья

Веб-приложение приюта для кошек и котов. Учебный проект по дисциплине «Введение в интернет-технологии» (собственная тема, практические работы № 1–4).

Посетители могут посмотреть каталог животных, отфильтровать их по параметрам, сохранить понравившихся в избранное, проверить погоду на день визита и оставить заявку на знакомство без регистрации. Куратор работает в закрытой админке: ведёт карточки питомцев, загружает фотогалереи, согласует встречи в календаре и выгружает статистику.

## Работающее приложение

| Раздел | Адрес |
| --- | --- |
| Сайт (HTTPS) | https://gerdifi.aweejobby.com:2083/ |
| Панель куратора | https://gerdifi.aweejobby.com:2083/admin.html |
| Проверка готовности (healthcheck) | https://gerdifi.aweejobby.com:2083/api/health |

**Тестовый аккаунт куратора для проверки:**
- Логин: `admin`
- Пароль: `admin`

## Что реализовано

- **Фронтенд (HTML5, CSS3, ES-модули JS):** семантическая разметка, один общий `style.css` без сторонних фреймворков, адаптивная сетка на Grid и Flexbox (проверено до ширины 360 px), локальные шрифты `Caveat` и `Nunito`.
- **Интерактивность и внешний API:** живой поиск (с нормализацией `ё` -> `е`), совместные фильтры по полу, возрасту в месяцах и характеру, сортировка, проверка форм с выводом ошибок под полями, избранное в `localStorage` и прогноз погоды для Санкт-Петербурга через Open-Meteo с резервным переключением на MET Norway и кэшированием на сервере.
- **Бэкенд и база данных (FastAPI + SQLite):** 25 HTTP-обработчиков, валидация запросов через Pydantic v2, параметризованные SQL-запросы, режим WAL и 7 связанных таблиц. Гостевые заявки не бронируют слот сразу — время занимает только подтверждённая куратором встреча (проверка вместимости идёт в транзакции `BEGIN IMMEDIATE`).
- **Панель куратора и безопасность:** авторизация для роли `admin`, пароли хешируются через `pwdlib` (Argon2), сессии хранятся в SQLite (cookie `HttpOnly` + `SameSite=Lax` + `Secure` в production), проверка `Origin`, `Host` и `X-CSRF-Token`, лимиты тела запроса. В админке работают загрузка фото (Pillow: проверка формата, удаление EXIF, ресайз до 1600 px и конвертация в WebP), недельный календарь, журнал истории заявок, SVG-график статистики, выгрузка CSV для Excel и раздел историй «Уже дома».
- **Развёртывание (Docker + HTTPS):** воспроизводимый `Dockerfile` от непривилегированного пользователя (UID `10001`), встроенный `HEALTHCHECK`, постоянный volume для SQLite и медиафайлов, полные ZIP-бэкапы с проверкой SHA-256 и развёртывание на Ubuntu 24.04 VPS за обратным прокси Nginx с TLS-сертификатом Let's Encrypt.

## Стек технологий

- **Клиент:** HTML5, CSS3, JavaScript (нативные ES-модули).
- **Сервер:** Python 3.12, FastAPI, Uvicorn, Pydantic v2, Pillow, `pwdlib` (`argon2-cffi`).
- **База данных:** SQLite 3 (WAL, `PRAGMA foreign_keys = ON`, схема v4).
- **Инфраструктура:** Docker, Docker Compose, Nginx / Caddy, GitHub Actions.

## Структура базы данных

Схема описана в `backend/schema.sql`. При первом запуске на пустой базе таблицы создаются автоматически и заполняются 15 стартовыми карточками питомцев из `backend/seed/pets.json`.

| Таблица | Основные поля и типы | Связи и назначение |
| --- | --- | --- |
| `users` | `id` (INT PK), `name`, `login` (TEXT UNIQUE), `password_hash` (TEXT, Argon2), `role`, `created_at` | Учётные записи кураторов (вход разрешён с ролью `admin`). |
| `pets` | `id` (INT PK), `slug` (UNIQUE), `name`, `age_months` (INT), `sex`, `temperament` (JSON TEXT), `trait`, `color`, `short`, `story`, `home`, `care`, `image`, `alt`, `featured` (0/1), `status`, `adoption_story`, `adopted_at` | Анкеты животных. Удаление мягкое — переводом в статус `archived`. |
| `pet_photos` | `id` (INT PK), `pet_id` (FK -> `pets.id`), `image`, `alt`, `position` (INT) | Галереи питомцев (до 12 фото на карточку, `ON DELETE RESTRICT`). |
| `applications` | `id` (INT PK), `user_id` (FK -> `users.id`, NULL), `pet_id` (FK -> `pets.id`), `visitor_name`, `phone`, `visit_date`, `visit_time`, `comment`, `status`, `admin_note`, `created_at` | Заявки на знакомство. Уникальный частичный индекс `applications_no_duplicate` защищает от дублей активных заявок. |
| `application_events` | `id` (INT PK), `application_id` (FK -> `applications.id`), `actor_id` (FK -> `users.id`), `kind`, `old_*` / `new_*`, `note`, `created_at` | Журнал создания, смены статусов, переносов и правок заметок по заявкам. |
| `messages` | `id` (INT PK), `user_id` (FK -> `users.id`, NULL), `name`, `topic`, `message`, `status`, `created_at` | Сообщения из формы обратной связи на странице контактов. |
| `sessions` | `token_hash` (TEXT PK, SHA-256), `user_id` (FK -> `users.id`), `csrf_token`, `expires_at` (INT) | Серверные сессии куратора на 12 часов (`ON DELETE CASCADE`). |

## Локальный запуск

### Через Docker (рекомендуемый способ)

Нужен установленный Docker Engine / Docker Desktop с Linux containers.

```bash
cp .env.example .env
docker compose up -d --build --wait
docker compose exec app python manage.py create-admin --if-missing
```

На Windows можно запустить `docker-start.bat` (остановка — `docker-stop.bat`). После запуска:
- сайт: `http://localhost:8000/`
- админка: `http://localhost:8000/admin.html`
- Swagger UI (в режиме разработки): `http://localhost:8000/api/docs`

Остановка с сохранением данных в volume `shelter-data`:

```bash
docker compose down
```

Не добавляйте флаг `-v`, если нужно сохранить локальную базу и загруженные фотографии.

### Напрямую через Python (без Docker)

Нужен Python 3.10 или новее. На Windows достаточно открыть `start.bat` — скрипт создаст `.venv`, установит зависимости из `requirements.txt`, предложит создать куратора и откроет браузер.

Запуск вручную в Linux / macOS / PowerShell:

```bash
python -m venv .venv
source .venv/bin/activate  # в Windows: .\.venv\Scripts\activate
pip install -r requirements.txt
python manage.py create-admin --if-missing
python serve.py
```

## Развёртывание на сервере (HTTPS)

1. **Автономно через Caddy (`compose.production.yaml`):** подходит для сервера со свободными портами 80 и 443. Скопируйте `.env.production.example` в `.env.production`, укажите `SITE_DOMAIN` и выполните:

```bash
docker compose --env-file .env.production -f compose.production.yaml up -d --build --wait
docker compose --env-file .env.production -f compose.production.yaml exec app python manage.py create-admin --if-missing
```

2. **За обратным прокси Nginx (текущий сервер):** контейнер публикуется только на `127.0.0.1:8000`, а Nginx принимает HTTPS с сертификатом Let's Encrypt и проксирует запросы с заголовками `Host`, `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto: https` и `client_max_body_size 50m`.

## Основные переменные окружения

| Переменная | Назначение |
| --- | --- |
| `HTTP_PORT` | Локальный порт Docker Compose (по умолчанию `8000`) |
| `SITE_DOMAIN` | Домен сайта для production-конфигурации |
| `SHELTER_ENV` | Режим работы: `development` или `production` |
| `SHELTER_PUBLIC_ORIGIN` | Внешний HTTPS-origin для проверки заголовка `Origin` |
| `SHELTER_ALLOWED_HOSTS` | Разрешённые домены `Host` через запятую |
| `SHELTER_SECURE_COOKIES` | `0` локально по HTTP, `1` на HTTPS |
| `SHELTER_API_DOCS` | Включение `/api/docs` (`1` локально, `0` в production) |
| `SHELTER_DB` | Путь к SQLite (в Docker `/app/data/shelter.sqlite3`) |
| `SHELTER_UPLOADS_DIR` | Папка загруженных WebP (в Docker `/app/data/uploads`) |
| `SHELTER_SLOT_CAPACITY` | Максимум подтверждённых встреч в одном интервале (1–8, по умолчанию `1`) |
| `SHELTER_TRUSTED_PROXIES` | Доверенные источники заголовков `X-Forwarded-*` |
| `WEATHER_USER_AGENT` | Заголовок `User-Agent` для запросов к погодному API |

## Резервное копирование и тесты

Создание полного ZIP-бэкапа (SQLite Backup API с учётом WAL, все загруженные WebP и `manifest.json` с SHA-256):

```bash
docker compose exec app python manage.py backup
docker compose cp app:/app/data/backups ./backups
```

Восстановление при остановленном контейнере:

```bash
docker compose stop app
docker compose run --rm --no-deps app python manage.py restore /app/data/backups/ИМЯ_АРХИВА.zip --confirm
docker compose up -d --wait app
```

Запуск автоматических тестов (50 Python-тестов + 4 проверки избранного + E2E-проверка Docker):

```bash
pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
node --test tests/test_favorites.mjs
python scripts/verify_docker.py
```

## Структура проекта

```text
ulitsa-koshachya/
  backend/          # FastAPI, модели Pydantic, SQLite/миграции, auth, загрузка фото
  frontend/         # HTML-страницы, style.css, 16 ES-модулей JS, локальные шрифты и фото
  scripts/          # healthcheck.py и проверка Docker verify_docker.py
  tests/            # Автотесты API, фич, миграций и избранного
  docs/             # Краткое ТЗ и набросок макета wireframe.svg
  Dockerfile        # Сборка контейнера (Python 3.12, UID 10001)
  compose.yaml      # Локальный запуск Docker Compose
  compose.production.yaml / Caddyfile  # Продакшен-сборка с Caddy
  manage.py         # CLI: create-admin, init, backup, restore
  serve.py / start.py / weather_backend.py
```
