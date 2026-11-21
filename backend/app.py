"""FastAPI: питомцы, учётные записи, заявки, сообщения и админка."""
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
import secrets
import sqlite3

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Settings, origin

from .database import (Database, ROOT, PET_STATUS, APPLICATION_STATUS,
                       INSERT_PET, UPDATE_PET, pet_values, serialize_pet, serialize_pets)
from .enhancements import feature_routes, record_event, slot_closed, slot_full
from .media import save_pet_details
from .request_limit import RequestLimitMiddleware
from .models import (Application, ApplicationStatus, Login, Message, MessageStatus,
                     MOSCOW, Pet)
from .security import (COOKIE_NAME, DUMMY_HASH, create_session, passwords, public_user,
                       read_session, require_admin, token_hash)
from weather_backend import WeatherService, WeatherUnavailable


def error(message, status=400, fields=None):
    return JSONResponse({'detail': message, 'fields': fields or {}}, status_code=status)


def application_json(row):
    item = dict(row)
    item['statusLabel'] = APPLICATION_STATUS[item['status']]
    return item


APPLICATION_SELECT = '''SELECT applications.*, pets.name AS pet_name, pets.slug AS pet_slug,
    pets.image AS pet_image FROM applications
    JOIN pets ON pets.id=applications.pet_id'''


def create_app(database_path=None, secure_cookies=None, settings=None):
    settings = settings or Settings.from_env()
    database = Database(database_path or settings.database)
    media_directory = settings.uploads or database.path.parent / 'uploads'

    @asynccontextmanager
    async def lifespan(app):
        database.initialize()
        media_directory.mkdir(parents=True, exist_ok=True)
        yield

    app = FastAPI(title='Улица Кошачья', version='4.0', lifespan=lifespan,
                  docs_url='/api/docs' if settings.api_docs else None, redoc_url=None,
                  openapi_url='/api/openapi.json' if settings.api_docs else None)
    app.state.database = database
    app.state.settings = settings
    app.state.media_directory = media_directory
    app.state.secure_cookies = settings.secure_cookies if secure_cookies is None else secure_cookies
    app.state.weather = WeatherService()

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exception):
        fields = {}
        for item in exception.errors():
            name = str(item['loc'][-1])
            text = item['msg'].removeprefix('Value error, ')
            fields[name] = text if any('а' <= char.lower() <= 'я' for char in text) else 'Проверьте значение этого поля.'
        return error('Проверьте заполнение полей.', 422, fields)

    @app.middleware('http')
    async def protect_requests(request, call_next):
        if request.url.path.startswith('/api/') and request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            source = request.headers.get('origin')
            if source:
                try:
                    same_origin = origin(source) == (settings.public_origin or origin(str(request.base_url)))
                except ValueError:
                    same_origin = False
                if not same_origin:
                    return error('Запрос с другого сайта отклонён.', 403)
            upload = request.url.path == '/api/admin/uploads' and request.method == 'POST'
            expected = 'multipart/form-data' if upload else 'application/json'
            if request.method != 'DELETE' and request.headers.get('content-type', '').split(';')[0] != expected:
                return error('Выберите фотографии для загрузки.' if upload else 'Сервер ожидает данные JSON.', 415)
            # Публичные формы не используют учётную запись и ничего не меняют от её имени.
            public_submission = request.method == 'POST' and request.url.path in ('/api/applications', '/api/messages')
            session = None if public_submission else read_session(request)
            if session and not secrets.compare_digest(request.headers.get('x-csrf-token', ''), session['csrf_token']):
                return error('Обновите страницу и повторите действие.', 403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        if request.url.path != '/api/docs':
            response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self' https://api.open-meteo.com; frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts), www_redirect=False)
    app.add_middleware(RequestLimitMiddleware)

    @app.get('/api/health', include_in_schema=False)
    def health():
        try:
            with database.connect() as db:
                db.execute('SELECT id FROM pets LIMIT 1').fetchone()
        except sqlite3.Error:
            return JSONResponse({'status': 'unavailable'}, status_code=503)
        return {'status': 'ok'}

    @app.get('/api/pets', tags=['Питомцы'])
    def pets():
        with database.connect() as db:
            rows = db.execute("SELECT * FROM pets WHERE status!='archived' ORDER BY id").fetchall()
            return serialize_pets(db, rows)

    @app.get('/api/pets/slug/{slug}', tags=['Питомцы'])
    def pet_by_slug(slug: str):
        with database.connect() as db:
            row = db.execute("SELECT * FROM pets WHERE slug=? AND status!='archived'", (slug,)).fetchone()
            pet = serialize_pets(db,[row])[0] if row else None
        if row is None:
            raise HTTPException(404, 'Питомец не найден или его карточка в архиве.')
        return pet

    @app.get('/api/pets/{pet_id}', tags=['Питомцы'])
    def pet_by_id(pet_id: int):
        with database.connect() as db:
            row = db.execute("SELECT * FROM pets WHERE id=? AND status!='archived'", (pet_id,)).fetchone()
            pet = serialize_pets(db,[row])[0] if row else None
        if row is None:
            raise HTTPException(404, 'Питомец не найден или его карточка в архиве.')
        return pet

    @app.post('/api/auth/login', tags=['Учётная запись'])
    def login(body: Login, request: Request, response: Response):
        with database.connect() as db:
            user = db.execute('SELECT * FROM users WHERE login=?', (body.login,)).fetchone()
        valid = passwords.verify(body.password, user['password_hash'] if user else DUMMY_HASH)
        if user is None or not valid or user['role'] != 'admin':
            raise HTTPException(401, 'Неверный логин или пароль.')
        return create_session(request, response, user)

    @app.get('/api/auth/me', tags=['Учётная запись'])
    def me(request: Request):
        user = read_session(request)
        return {'user': public_user(user) if user else None,
                'csrfToken': user['csrf_token'] if user else None}

    @app.post('/api/auth/logout', tags=['Учётная запись'])
    def logout(request: Request, response: Response):
        with database.connect() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?',
                       (token_hash(request.cookies.get(COOKIE_NAME, '')),))
        response.delete_cookie(COOKIE_NAME, path='/', httponly=True, samesite='lax',
                               secure=app.state.secure_cookies)
        return {'ok': True}

    @app.post('/api/applications', status_code=201, tags=['Заявки'])
    def create_application(body: Application):
        now = datetime.now(MOSCOW)
        if body.visit_date == now.date().isoformat() and int(body.visit_time[:2]) * 60 <= now.hour * 60 + now.minute:
            return error('Выбранное время уже прошло.', 422, {'visit_time': 'Выберите более поздний интервал или день.'})
        try:
            with database.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                pet = db.execute('SELECT status FROM pets WHERE id=?', (body.pet_id,)).fetchone()
                if pet is None or pet['status'] != 'available':
                    return error('С этим питомцем сейчас нельзя записаться на знакомство. Обновите список.', 409)
                if slot_full(db,body.visit_date,body.visit_time,settings.slot_capacity):
                    return error('Это время уже занято. Выберите другой интервал.', 409, {'visit_time':'Выберите свободное время.'})
                duplicate = db.execute('''SELECT 1 FROM applications
                    WHERE phone=? AND pet_id=? AND visit_date=? AND visit_time=?
                    AND status IN ('new','confirmed')''',
                    (body.phone, body.pet_id, body.visit_date, body.visit_time)).fetchone()
                if duplicate:
                    return error('Заявка с этим телефоном на выбранные день и время уже принята. Дождитесь звонка куратора.', 409)
                cursor = db.execute('''INSERT INTO applications
                    (user_id,pet_id,visitor_name,phone,visit_date,visit_time,comment)
                    VALUES (?,?,?,?,?,?,?)''', (None, body.pet_id, body.visitor_name,
                    body.phone, body.visit_date, body.visit_time, body.comment))
                record_event(db,cursor.lastrowid,'created')
        except sqlite3.IntegrityError:
            return error('Такая активная заявка уже принята. Дождитесь звонка куратора.', 409)
        return {'id': cursor.lastrowid, 'status': 'new'}

    @app.post('/api/messages', status_code=201, tags=['Обратная связь'])
    def create_message(body: Message):
        with database.connect() as db:
            cursor = db.execute('INSERT INTO messages(user_id,name,topic,message) VALUES (?,?,?,?)',
                                (None, body.name, body.topic, body.message))
        return {'id': cursor.lastrowid, 'status': 'new'}

    @app.get('/api/admin/pets', tags=['Админка'])
    def admin_pets(user=Depends(require_admin)):
        with database.connect() as db:
            rows = db.execute('SELECT * FROM pets ORDER BY id').fetchall()
            return serialize_pets(db,rows)

    @app.get('/api/admin/photos', tags=['Админка'])
    def admin_photos(user=Depends(require_admin)):
        files = [path for folder in [ROOT / 'frontend' / 'images', ROOT / 'frontend' / 'images' / 'pets']
                 for path in folder.glob('*') if path.suffix in ('.jpg', '.png', '.webp') and path.stem not in ('logo', 'shelter')]
        return sorted(str(path.relative_to(ROOT / 'frontend')).replace('\\', '/') for path in files) + [
            'media/'+path.name for path in sorted(media_directory.glob('*.webp')) if not path.is_symlink()]

    @app.post('/api/admin/pets', status_code=201, tags=['Админка'])
    def add_pet(body: Pet, user=Depends(require_admin)):
        try:
            with database.connect() as db:
                cursor = db.execute(INSERT_PET, pet_values(body.model_dump()))
                save_pet_details(db,cursor.lastrowid,body,media_directory)
                pet = db.execute('SELECT * FROM pets WHERE id=?', (cursor.lastrowid,)).fetchone()
                result = serialize_pets(db,[pet])[0]
        except sqlite3.IntegrityError:
            return error('Такой адрес карточки уже занят. Измените короткое имя.', 409, {'slug': 'Выберите другое короткое имя.'})
        return result

    @app.put('/api/admin/pets/{pet_id}', tags=['Админка'])
    def edit_pet(pet_id: int, body: Pet, user=Depends(require_admin)):
        try:
            with database.connect() as db:
                previous = db.execute('SELECT * FROM pets WHERE id=?',(pet_id,)).fetchone()
                cursor = db.execute(UPDATE_PET, pet_values(body.model_dump()) + (pet_id,))
                if not cursor.rowcount:
                    raise HTTPException(404, 'Питомец не найден.')
                save_pet_details(db,pet_id,body,media_directory,previous)
                pet = db.execute('SELECT * FROM pets WHERE id=?', (pet_id,)).fetchone()
                result = serialize_pets(db,[pet])[0]
        except sqlite3.IntegrityError:
            return error('Такой адрес карточки уже занят.', 409, {'slug': 'Выберите другое короткое имя.'})
        return result

    @app.delete('/api/admin/pets/{pet_id}', tags=['Админка'])
    def archive_pet(pet_id: int, user=Depends(require_admin)):
        with database.connect() as db:
            cursor = db.execute("UPDATE pets SET status='archived' WHERE id=?", (pet_id,))
            if not cursor.rowcount:
                raise HTTPException(404, 'Питомец не найден.')
        return {'ok': True}

    @app.get('/api/admin/applications', tags=['Админка'])
    def admin_applications(user=Depends(require_admin)):
        with database.connect() as db:
            rows = db.execute(APPLICATION_SELECT + ' ORDER BY applications.id DESC').fetchall()
        return [application_json(row) for row in rows]

    @app.patch('/api/admin/applications/{application_id}', tags=['Админка'])
    def update_application(application_id: int, body: ApplicationStatus, user=Depends(require_admin)):
        transitions = {'new': {'new', 'confirmed', 'cancelled'},
                       'confirmed': {'confirmed', 'completed', 'cancelled'},
                       'completed': {'completed'}, 'cancelled': {'cancelled'}}
        with database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM applications WHERE id=?', (application_id,)).fetchone()
            if row is None:
                raise HTTPException(404, 'Заявка не найдена.')
            if body.status not in transitions[row['status']]:
                raise HTTPException(409, 'Этот переход статуса недоступен. Обновите список.')
            day,slot = body.visit_date or row['visit_date'], body.visit_time or row['visit_time']
            changed_slot = (day,slot) != (row['visit_date'],row['visit_time'])
            if changed_slot and row['status'] in ('completed','cancelled'):
                raise HTTPException(409, 'Завершённую или отменённую встречу нельзя переносить.')
            if changed_slot or (body.status == 'confirmed' and row['status'] != 'confirmed'):
                problem = slot_closed(day,slot)
                if problem:
                    raise HTTPException(422, problem)
                if body.status in ('new','confirmed') and slot_full(db,day,slot,settings.slot_capacity,application_id):
                    raise HTTPException(409, 'В этом интервале уже есть подтверждённая встреча. Выберите другое время.')
            duplicate = db.execute('''SELECT 1 FROM applications WHERE id!=? AND phone=? AND pet_id=?
                AND visit_date=? AND visit_time=? AND status IN ('new','confirmed')''',
                (application_id,row['phone'],row['pet_id'],day,slot)).fetchone()
            if duplicate and body.status in ('new','confirmed'):
                raise HTTPException(409, 'Для этого телефона уже есть активная заявка на тот же визит.')
            db.execute('UPDATE applications SET status=?,admin_note=?,visit_date=?,visit_time=? WHERE id=?',
                       (body.status, body.admin_note,day,slot,application_id))
            if changed_slot or body.status != row['status'] or body.admin_note != row['admin_note']:
                record_event(db,application_id,'updated',user['id'],row)
        return {'ok': True}

    @app.get('/api/admin/messages', tags=['Админка'])
    def admin_messages(user=Depends(require_admin)):
        with database.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM messages ORDER BY id DESC').fetchall()]

    @app.patch('/api/admin/messages/{message_id}', tags=['Админка'])
    def update_message(message_id: int, body: MessageStatus, user=Depends(require_admin)):
        with database.connect() as db:
            cursor = db.execute('UPDATE messages SET status=? WHERE id=?', (body.status, message_id))
            if not cursor.rowcount:
                raise HTTPException(404, 'Сообщение не найдено.')
        return {'ok': True}

    app.include_router(feature_routes(database,settings,media_directory))

    @app.get('/api/weather', tags=['Погода'])
    def weather():
        try:
            return app.state.weather.get_forecast()
        except WeatherUnavailable:
            return error('Источники погоды сейчас недоступны. Попробуйте позже.', 502)

    @app.api_route('/api/{path:path}', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'], include_in_schema=False)
    def unknown_api(path: str):
        raise HTTPException(404, 'Такого адреса API нет.')

    @app.get('/account.html', include_in_schema=False)
    def old_account_bookmark():
        return RedirectResponse('/admin-login.html', status_code=302)

    # Открывается только frontend: файл SQLite и Python-исходники наружу не раздаются.
    app.mount('/media', StaticFiles(directory=str(media_directory), check_dir=False), name='media')
    app.mount('/', StaticFiles(directory=str(ROOT / 'frontend'), html=True), name='frontend')
    return app


app = create_app()
