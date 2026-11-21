"""Администратор и резервные копии. Пароли не передаются в аргументах команд."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import re
import shutil
import sys
from tempfile import TemporaryDirectory
import uuid
import zipfile

from backend.config import Settings
from backend.database import Database


def check_backup(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError('Файл резервной копии не найден.')
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Проверка целостности SQLite не пройдена.')
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('В копии нарушены связи таблиц.')
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'users', 'pets', 'applications', 'messages', 'sessions'} <= tables:
            raise ValueError('Этот файл не является базой приюта.')
        required = {
            'users': {'id', 'name', 'password_hash', 'role', 'created_at'},
            'pets': {'id', 'slug', 'name', 'age_months', 'sex', 'temperament', 'trait',
                     'color', 'short', 'story', 'home', 'care', 'image', 'alt', 'featured', 'status'},
            'applications': {'id', 'user_id', 'pet_id', 'visitor_name', 'phone', 'visit_date',
                             'visit_time', 'comment', 'status', 'admin_note', 'created_at'},
            'messages': {'id', 'user_id', 'name', 'topic', 'message', 'status', 'created_at'},
            'sessions': {'token_hash', 'user_id', 'csrf_token', 'expires_at'},
        }
        for table, fields in required.items():
            columns = {row[1] for row in db.execute(f'PRAGMA table_info({table})')}
            if not fields <= columns or (table == 'users' and not {'login', 'email'} & columns):
                raise ValueError('Схема копии несовместима с приложением.')
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version > 4:
            raise ValueError('Копия создана более новой версией схемы.')
        if version == 4 and not {'pet_photos','application_events'} <= tables:
            raise ValueError('В копии не хватает таблиц галерей или истории.')
        if version == 4:
            required_features = {
                'pets': {'adoption_story','adopted_at'},
                'pet_photos': {'id','pet_id','image','alt','position'},
                'application_events': {'id','application_id','actor_id','kind','old_status','new_status',
                    'old_visit_date','new_visit_date','old_visit_time','new_visit_time','old_note','note','created_at'},
            }
            for table, fields in required_features.items():
                if not fields <= {row[1] for row in db.execute(f'PRAGMA table_info({table})')}:
                    raise ValueError('В копии несовместимая схема галерей или истории.')
    return path


def backup_database(database, directory=None, prefix='shelter'):
    if not database.path.is_file():
        raise ValueError('Рабочая база ещё не создана. Сначала запустите приложение.')
    destination = Path(directory or database.path.parent / 'backups')
    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    path = destination / f'{prefix}-{stamp}-{uuid.uuid4().hex[:8]}.sqlite3'
    temporary = path.with_suffix('.tmp')
    try:
        with database.connect() as source, sqlite3.connect(temporary) as target:
            source.backup(target)
        check_backup(temporary)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def restore_database(database, source, confirmed=False, backup_previous=True):
    if not confirmed:
        raise ValueError('Сначала остановите приложение. Для восстановления добавьте --confirm.')
    source = check_backup(source)
    if source == database.path.resolve():
        raise ValueError('Источник и рабочая база должны быть разными файлами.')
    database.path.parent.mkdir(parents=True, exist_ok=True)
    # Сначала переносим и мигрируем копию отдельно, не меняя рабочую базу при ошибке схемы.
    with TemporaryDirectory(prefix='restore-', dir=database.path.parent) as directory:
        staged = Database(Path(directory) / 'staged.sqlite3')
        with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as source_db:
            with sqlite3.connect(staged.path) as target:
                source_db.backup(target)
        staged.initialize()
        check_backup(staged.path)
        previous = backup_database(database, prefix='before-restore') if database.path.is_file() and backup_previous else None
        # SQLite backup переносит согласованный снимок, включая данные из WAL.
        # Файлы WAL не удаляем вручную; приложение по инструкции должно быть остановлено.
        with staged.connect() as source_db, sqlite3.connect(database.path) as target:
            source_db.backup(target)
    return previous


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def referenced_media(path):
    with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True) as db:
        images = {row[0] for row in db.execute('SELECT image FROM pets')}
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='pet_photos'").fetchone():
            images.update(row[0] for row in db.execute('SELECT image FROM pet_photos'))
    return {value.split('/',1)[1] for value in images if value.startswith('media/')}


def backup_project(database, media, directory=None, prefix='shelter'):
    destination = Path(directory or database.path.parent/'backups')
    destination.mkdir(parents=True,exist_ok=True)
    name = f'{prefix}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}-{uuid.uuid4().hex[:8]}.zip'
    target = destination/name
    temporary = target.with_suffix('.tmp')
    try:
        with TemporaryDirectory(prefix='snapshot-') as folder:
            snapshot = backup_database(database,Path(folder))
            files = {'shelter.sqlite3':snapshot}
            if Path(media).is_dir():
                for photo in Path(media).glob('*.webp'):
                    if not photo.is_symlink() and re.fullmatch(r'[a-f0-9]{32}\.webp',photo.name):
                        files['uploads/'+photo.name] = photo
            if any('uploads/'+name not in files for name in referenced_media(snapshot)):
                raise ValueError('В рабочей папке не хватает фото, на которое ссылается база. Проверьте SHELTER_UPLOADS_DIR.')
            manifest = {'format':'ulitsa-koshachya-backup-v1','files':{key:file_hash(path) for key,path in files.items()}}
            with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                for key,path in files.items():archive.write(path,key)
                archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def restore_project(database, media, source, confirmed=False):
    if not confirmed:
        raise ValueError('Остановите приложение и добавьте --confirm.')
    source = Path(source)
    if source.suffix.lower() != '.zip':
        check_backup(source)
        if any(not (Path(media)/name).is_file() for name in referenced_media(source)):
            raise ValueError('Для этой базы нужны загруженные фото. Восстановите полную ZIP-копию или перенесите uploads.')
        previous = backup_project(database,media,prefix='before-restore') if database.path.is_file() else None
        restore_database(database,source,confirmed=True,backup_previous=False)
        return previous
    with TemporaryDirectory(prefix='import-') as folder:
        staging = Path(folder)
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            names = [item.filename for item in entries]
            if len(names)!=len(set(names)) or len(names)>10000 or sum(item.file_size for item in entries)>512*1024*1024:
                raise ValueError('Архив повреждён или превышает допустимый размер 512 МБ.')
            if not {'manifest.json','shelter.sqlite3'} <= set(names):
                raise ValueError('В архиве нет манифеста и базы приюта.')
            for entry in entries:
                name = entry.filename
                if name not in ('manifest.json','shelter.sqlite3') and not re.fullmatch(r'uploads/[a-f0-9]{32}\.webp',name):
                    raise ValueError('Недопустимый путь в архиве.')
                output = staging/name
                output.parent.mkdir(parents=True,exist_ok=True)
                with archive.open(entry) as incoming, output.open('wb') as outgoing:
                    shutil.copyfileobj(incoming,outgoing,1024*1024)
        manifest = json.loads((staging/'manifest.json').read_text(encoding='utf-8'))
        if manifest.get('format')!='ulitsa-koshachya-backup-v1' or set(manifest.get('files',{}))!=set(names)-{'manifest.json'}:
            raise ValueError('Некорректный манифест копии.')
        if any(file_hash(staging/name)!=digest for name,digest in manifest['files'].items()):
            raise ValueError('Контрольная сумма файла не совпадает.')
        check_backup(staging/'shelter.sqlite3')
        if any(not (staging/'uploads'/name).is_file() for name in referenced_media(staging/'shelter.sqlite3')):
            raise ValueError('В архиве не хватает фотографий из базы.')
        # Проверяем миграцию до любых изменений рабочей папки.
        staged_db = Database(staging/'shelter.sqlite3')
        staged_db.initialize()
        previous = backup_project(database,media,prefix='before-restore') if database.path.is_file() else None
        media = Path(media)
        media.mkdir(parents=True,exist_ok=True)
        for path in (staging/'uploads').glob('*.webp'):
            target = media/path.name
            if target.exists() and file_hash(target)!=file_hash(path):
                raise ValueError('Фото с таким именем уже существует и отличается. Рабочая база не изменена.')
            if not target.exists():
                temporary = target.with_suffix('.tmp')
                shutil.copyfile(path,temporary)
                temporary.replace(target)
        restore_database(database,staged_db.path,confirmed=True,backup_previous=False)
        return previous


def admin_from_env(database, values=None):
    from backend.models import AdminAccount
    from backend.security import passwords
    values = os.environ if values is None else values
    login = values.get('SHELTER_ADMIN_LOGIN', '')
    password = values.get('SHELTER_ADMIN_PASSWORD', '')
    if not login or not password:
        raise ValueError('Задайте SHELTER_ADMIN_LOGIN и SHELTER_ADMIN_PASSWORD в окружении команды.')
    account = AdminAccount(name=values.get('SHELTER_ADMIN_NAME') or 'Куратор', login=login, password=password)
    try:
        with database.connect() as db:
            db.execute("INSERT INTO users(name,login,password_hash,role) VALUES (?,?,?,'admin')",
                       (account.name, account.login, passwords.hash(account.password)))
    except sqlite3.IntegrityError:
        raise ValueError('Этот логин уже занят. Действующий пароль не изменён.') from None


def main(argv=None):
    os.umask(0o077)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Управление проектом «Улица Кошачья»')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init', help='Создать или обновить схему и начальных питомцев')
    admin = commands.add_parser('create-admin', help='Создать администратора, не меняя существующих')
    admin.add_argument('--from-env', action='store_true', help='Взять данные из SHELTER_ADMIN_* вместо ввода')
    admin.add_argument('--if-missing', action='store_true', help='Пропустить, если администратор уже есть')
    backup = commands.add_parser('backup', help='ZIP-копия SQLite и загруженных фотографий')
    backup.add_argument('--directory', type=Path)
    restore = commands.add_parser('restore', help='Восстановить копию при остановленном приложении')
    restore.add_argument('source', type=Path)
    restore.add_argument('--confirm', action='store_true')
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env()
        database = Database(settings.database)
        media = settings.uploads or database.path.parent/'uploads'
        if args.command == 'backup':
            print('Резервная копия базы и фотографий:', backup_project(database, media, args.directory))
        elif args.command == 'restore':
            previous = restore_project(database, media, args.source, args.confirm)
            print('База восстановлена. Резервная копия прежнего состояния:', previous or 'базы ещё не было')
        else:
            database.initialize()
            if args.command == 'create-admin':
                if args.if_missing and database.has_admin():
                    print('Администратор уже есть. Его данные не изменены.')
                elif args.from_env:
                    admin_from_env(database)
                    print('Администратор создан.')
                else:
                    from start import create_admin
                    create_admin(database)
            else:
                print('База готова.')
    except Exception as error:
        # ValidationError может содержать input_value пароля: его в журнал не выводим.
        from pydantic import ValidationError
        if isinstance(error, ValidationError):
            message = 'Проверьте имя, логин и непустой пароль до 128 символов.'
        elif isinstance(error, (ValueError, OSError, sqlite3.Error, zipfile.BadZipFile)):
            message = str(error)
        else:
            raise
        print('Не выполнено:', message, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
