"""Проверка релиза на машине с Docker. Рабочие контейнеры и данные не затрагивает.

Запуск из корня проекта: python scripts/verify_docker.py
"""
from datetime import datetime, timedelta, timezone
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener
import uuid

ROOT = Path(__file__).resolve().parents[1]


def command(*args, input=None, timeout=120, env=None, required=True):
    result = subprocess.run(args, cwd=ROOT, input=input, capture_output=True,
                            text=True, encoding='utf-8', errors='replace', timeout=timeout, env=env)
    if required and result.returncode:
        raise RuntimeError(f'Не выполнено: {args[0]} {args[1]}\n{result.stderr[-3000:]}\n{result.stdout[-1000:]}')
    return result.stdout.strip()


def verify():
    if not shutil.which('docker'):
        raise RuntimeError('Docker не найден. Установите и запустите Docker Desktop с Linux containers.')
    command('docker', 'info', timeout=20)
    command('docker', 'compose', '--env-file', '.env.example', 'config', '--quiet')
    environment = dict(os.environ, SITE_DOMAIN='cats.example.org')
    command('docker', 'compose', '--env-file', '.env.production.example', '-f',
            'compose.production.yaml', 'config', '--quiet', env=environment)

    suffix = uuid.uuid4().hex[:12]
    image, container, volume = f'ulitsa-verify:{suffix}', f'ulitsa-verify-{suffix}', f'ulitsa-verify-data-{suffix}'
    guest, admin = build_opener(), build_opener(HTTPCookieProcessor(CookieJar()))
    base = ''
    checks = []

    def request(path, body=None, method='GET', authenticated=False, csrf=None, expected=200,
                raw=None, content_type=None, binary=False):
        headers = {'Accept': 'application/json'}
        if body is not None:
            headers.update({'Content-Type': 'application/json', 'Origin': base})
        if raw is not None:
            headers.update({'Content-Type':content_type,'Origin':base})
        if csrf:
            headers['X-CSRF-Token'] = csrf
        req = Request(base + path, data=raw if raw is not None else json.dumps(body).encode() if body is not None else None,
                      headers=headers, method=method)
        try:
            response = (admin if authenticated else guest).open(req, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            value = response.read()
            if response.code != expected:
                raise RuntimeError(f'{method} {path}: {response.code}, ожидалось {expected}.')
            return value if binary else json.loads(value)

    def start_container():
        nonlocal base
        command('docker', 'run', '-d', '--name', container, '--cap-drop=ALL',
                '--security-opt=no-new-privileges:true', '-p', '127.0.0.1::8000',
                '-v', f'{volume}:/app/data', image)
        details = json.loads(command('docker', 'inspect', container))[0]
        port = details['NetworkSettings']['Ports']['8000/tcp'][0]['HostPort']
        base = f'http://127.0.0.1:{port}'
        deadline = time.monotonic() + 50
        while time.monotonic() < deadline:
            try:
                request('/api/health')
                return
            except (URLError, ConnectionError, TimeoutError, RuntimeError):
                time.sleep(0.5)
        raise RuntimeError('Контейнер не стал готов за 50 секунд.')

    try:
        print('Проверяем сборку образа…', flush=True)
        command('docker', 'build', '-t', image, '.', timeout=900)
        checks.append('Docker image built')
        command('docker', 'volume', 'create', volume)
        start_container()
        if command('docker', 'exec', container, 'id', '-u') != '10001':
            raise RuntimeError('Приложение должно работать от пользователя 10001.')
        if len(request('/api/pets')) != 15:
            raise RuntimeError('В чистой базе должно быть 15 питомцев.')
        checks.append('Healthy non-root container; 15 pets seeded')
        request('/api/admin/applications', expected=401)
        request('/api/auth/register', {}, 'POST', expected=404)
        day = datetime.now(timezone(timedelta(hours=3))).date() + timedelta(days=2)
        if day.weekday() == 0:
            day += timedelta(days=1)
        body = {'pet_id': 1, 'visitor_name': 'Посетитель', 'phone': '+79000000000',
                'visit_date': day.isoformat(), 'visit_time': '14-16', 'confirmed': True}
        receipt = request('/api/applications', body, 'POST', expected=201)
        if set(receipt) != {'id', 'status'}:
            raise RuntimeError('Публичный ответ должен содержать только номер и статус.')
        request('/api/applications', body, 'POST', expected=409)
        checks.append('Guest submission, duplicate prevention and protected admin API')

        password = secrets.token_urlsafe(24)
        credentials = {'SHELTER_ADMIN_LOGIN':'verify', 'SHELTER_ADMIN_PASSWORD':password,
                       'SHELTER_ADMIN_NAME':'Куратор'}
        script = ('import json,sys; from manage import admin_from_env; '
                  'from backend.config import Settings; from backend.database import Database; '
                  'admin_from_env(Database(Settings.from_env().database),json.load(sys.stdin))')
        command('docker', 'exec', '-i', container, 'python', '-c', script, input=json.dumps(credentials))
        login = request('/api/auth/login', {'login':'verify','password':password}, 'POST', authenticated=True)
        items = request('/api/admin/applications', authenticated=True)
        if items[0]['id'] != receipt['id'] or items[0]['user_id'] is not None:
            raise RuntimeError('Администратор не увидел гостевую заявку.')
        request(f"/api/admin/applications/{receipt['id']}",
                {'status':'confirmed', 'admin_note':'Проверка контейнерного запуска.'},
                'PATCH', authenticated=True, csrf=login['csrfToken'])
        history=request(f"/api/admin/applications/{receipt['id']}/history",authenticated=True)
        if [item['kind'] for item in history] != ['created','updated']:
            raise RuntimeError('Не сохранилась история создания и подтверждения заявки.')
        availability=request(f'/api/availability?date={day.isoformat()}&pet_id=1')
        if next(slot for slot in availability['slots'] if slot['value']=='14-16')['available']:
            raise RuntimeError('Подтверждённая встреча должна занимать интервал.')
        calendar=request(f'/api/admin/calendar?from={day.isoformat()}&to={day.isoformat()}',authenticated=True)
        if calendar['items'][0]['id'] != receipt['id']:
            raise RuntimeError('Календарь не получил заявку.')
        statistics=request('/api/admin/statistics',authenticated=True)
        if statistics['totals']['all'] != 1:
            raise RuntimeError('Статистика не учитывает заявку.')
        if not request('/api/admin/applications.csv',authenticated=True,binary=True).startswith(b'\xef\xbb\xbf'):
            raise RuntimeError('CSV должен иметь UTF-8 BOM для Excel.')
        boundary='verify-'+uuid.uuid4().hex
        multipart=(f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="persik.jpg"\r\n'
                   'Content-Type: image/jpeg\r\n\r\n').encode()+(ROOT/'frontend/images/persik.jpg').read_bytes()+f'\r\n--{boundary}--\r\n'.encode()
        photos=request('/api/admin/uploads',method='POST',authenticated=True,csrf=login['csrfToken'],expected=201,
                       raw=multipart,content_type='multipart/form-data; boundary='+boundary)
        pet=request('/api/pets/1')
        fields=('slug','name','ageMonths','sex','temperament','trait','color','short','story','home','care','image','alt','featured','status')
        pet_body={key:pet[key] for key in fields}
        pet_body.update(image=photos[0]['image'],photos=[{'image':photos[0]['image'],'alt':'Персик'}])
        request('/api/admin/pets/1',pet_body,'PUT',authenticated=True,csrf=login['csrfToken'])
        command('docker', 'exec', container, 'python', 'manage.py', 'backup')
        # Восстановление проверяем в отдельной временной папке внутри проверочного контейнера.
        restore_script=('from pathlib import Path; from tempfile import TemporaryDirectory; '
            'from manage import restore_project; from backend.database import Database; '
            'source=max(Path("data/backups").glob("shelter-*.zip"),key=lambda p:p.stat().st_mtime); '
            'temp=TemporaryDirectory(); db=Database(Path(temp.name)/"shelter.sqlite3"); '
            'restore_project(db,Path(temp.name)/"uploads",source,confirmed=True); '
            'assert list((Path(temp.name)/"uploads").glob("*.webp")); '
            'assert db.path.is_file(); temp.cleanup()')
        command('docker','exec',container,'python','-c',restore_script)
        checks.append('History, capacity, calendar, statistics, CSV, image upload and full ZIP restore')
        command('docker', 'rm', '-f', container)
        start_container()
        # Сессия и заявка должны пережить создание нового контейнера с тем же volume.
        items = request('/api/admin/applications', authenticated=True)
        if len(items) != 1 or items[0]['status'] != 'confirmed':
            raise RuntimeError('Заявка или сессия не сохранилась при пересоздании контейнера.')
        if request('/api/pets/1')['image'] != photos[0]['image'] or not request('/'+photos[0]['image'],binary=True):
            raise RuntimeError('Загруженная фотография не пережила пересоздание контейнера.')
        checks.append('Session, application, gallery and uploaded image survived container recreation')

        caddy_image = 'caddy:2.10.2-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d'
        command('docker', 'run', '--rm', '-e', 'SITE_DOMAIN=cats.example.org',
                '-v', f'{ROOT / "Caddyfile"}:/etc/caddy/Caddyfile:ro',
                caddy_image, 'caddy', 'validate', '--config', '/etc/caddy/Caddyfile',
                '--adapter', 'caddyfile', timeout=180)
        checks.append('Both Compose files and Caddy configuration validated')
    except Exception:
        logs = command('docker', 'logs', '--tail', '40', container, required=False)
        if logs:
            print(logs, file=sys.stderr)
        raise
    finally:
        # Удаляем только объекты с уникальными именами, созданные этой проверкой.
        command('docker', 'rm', '-f', container, required=False)
        command('docker', 'volume', 'rm', volume, required=False)
        command('docker', 'image', 'rm', image, required=False)
    print(json.dumps({'status':'passed','checks':checks}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        verify()
    except Exception as error:
        print('Проверка не завершена:', error, file=sys.stderr)
        raise SystemExit(1)
