"""SQLite: отдельное подключение для каждой операции и параметризованный SQL."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import json
import re
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
PET_STATUS = {'available': 'Ищет дом', 'reserved': 'Знакомится с семьёй',
              'adopted': 'Уже дома', 'archived': 'В архиве'}
APPLICATION_STATUS = {'new': 'Новая', 'confirmed': 'Встреча согласована',
                      'completed': 'Знакомство состоялось', 'cancelled': 'Отменена'}
PET_VALUES = ('slug', 'name', 'ageMonths', 'sex', 'temperament', 'trait', 'color',
              'short', 'story', 'home', 'care', 'image', 'alt', 'featured', 'status')
INSERT_PET = '''INSERT INTO pets
    (slug,name,age_months,sex,temperament,trait,color,short,story,home,care,image,alt,featured,status)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)'''
UPDATE_PET = '''UPDATE pets SET
    slug=?,name=?,age_months=?,sex=?,temperament=?,trait=?,color=?,short=?,story=?,home=?,
    care=?,image=?,alt=?,featured=?,status=? WHERE id=?'''


def pet_values(pet):
    values = dict(pet)
    values['temperament'] = json.dumps(values['temperament'], ensure_ascii=False)
    values['featured'] = int(values['featured'])
    return tuple(values[key] for key in PET_VALUES)


def russian_age(months):
    years = months // 12
    value = months if months < 12 else years
    forms = ('месяц', 'месяца', 'месяцев') if months < 12 else ('год', 'года', 'лет')
    ending = 2 if 11 <= value % 100 <= 14 else (0 if value % 10 == 1 else 1 if 2 <= value % 10 <= 4 else 2)
    return f'{value} {forms[ending]}'


def serialize_pet(row, photos=None):
    pet = dict(row)
    pet['ageMonths'] = pet.pop('age_months')
    pet['age'] = russian_age(pet['ageMonths'])
    pet['sexLabel'] = 'Кошка' if pet['sex'] == 'female' else 'Кот'
    pet['temperament'] = json.loads(pet['temperament'])
    pet['featured'] = bool(pet['featured'])
    pet['statusLabel'] = PET_STATUS[pet['status']]
    pet['adoptionStory'] = pet.pop('adoption_story', '')
    pet['adoptedAt'] = pet.pop('adopted_at', '')
    pet['photos'] = photos if photos is not None else [{'image':pet['image'], 'alt':pet['alt'], 'position':0}]
    return pet


def serialize_pets(db, rows):
    photos = {}
    for row in db.execute('SELECT * FROM pet_photos ORDER BY position,id'):
        photos.setdefault(row['pet_id'], []).append({key:row[key] for key in ('id','image','alt','position')})
    return [serialize_pet(row, photos.get(row['id'])) for row in rows]


def fill_feature_data(db):
    db.execute('''INSERT INTO pet_photos(pet_id,image,alt,position)
        SELECT id,image,alt,0 FROM pets WHERE NOT EXISTS
        (SELECT 1 FROM pet_photos WHERE pet_id=pets.id)''')
    db.execute('''INSERT INTO application_events
        (application_id,kind,new_status,new_visit_date,new_visit_time,note)
        SELECT id,'imported',status,visit_date,visit_time,admin_note FROM applications
        WHERE NOT EXISTS (SELECT 1 FROM application_events WHERE application_id=applications.id)''')


class Database:
    def __init__(self, path=None):
        self.path = Path(path or ROOT / 'data' / 'shelter.sqlite3')

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            if db.execute('PRAGMA user_version').fetchone()[0] > 4:
                raise ValueError('База создана более новой версией сайта. Обновите приложение перед запуском.')
            db.execute('PRAGMA journal_mode = WAL')
            self.migrate_accounts(db)
            self.migrate_guest_applications(db)
            self.migrate_features(db)
            db.executescript((ROOT / 'backend' / 'schema.sql').read_text(encoding='utf-8'))
            if db.execute('SELECT COUNT(*) FROM pets').fetchone()[0] == 0:
                pets = json.loads((ROOT / 'backend' / 'seed' / 'pets.json').read_text(encoding='utf-8'))
                for pet in pets:
                    pet.setdefault('status', 'available')
                    db.execute(INSERT_PET, pet_values(pet))
            fill_feature_data(db)
            db.execute('PRAGMA user_version = 4')

    def migrate_features(self, db):
        columns = {row['name'] for row in db.execute('PRAGMA table_info(pets)')}
        if not columns or 'adoption_story' in columns:
            return
        backups = self.path.parent / 'backups'
        backups.mkdir(exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        with sqlite3.connect(backups / f'before-features-{timestamp}.sqlite3') as backup:
            db.backup(backup)
        db.execute('BEGIN IMMEDIATE')
        db.execute("ALTER TABLE pets ADD COLUMN adoption_story TEXT NOT NULL DEFAULT ''")
        db.execute("ALTER TABLE pets ADD COLUMN adopted_at TEXT NOT NULL DEFAULT ''")
        schema = (ROOT / 'backend' / 'schema.sql').read_text(encoding='utf-8')
        for statement in schema[schema.index('CREATE TABLE IF NOT EXISTS pet_photos'):].split(';'):
            if statement.strip():
                db.execute(statement)
        fill_feature_data(db)
        db.execute('PRAGMA user_version=4')
        db.commit()

    def migrate_guest_applications(self, db):
        """Разрешаем заявки без аккаунта; старые связи, номера и заметки сохраняются."""
        columns = {row['name']: row for row in db.execute('PRAGMA table_info(applications)')}
        if not columns or not columns['user_id']['notnull']:
            return
        backups = self.path.parent / 'backups'
        backups.mkdir(exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        with sqlite3.connect(backups / f'before-guest-applications-{timestamp}.sqlite3') as backup:
            db.backup(backup)

        # В SQLite NOT NULL меняется пересозданием таблицы. Все шаги — в одной транзакции.
        schema = (ROOT / 'backend' / 'schema.sql').read_text(encoding='utf-8')
        start = schema.index('CREATE TABLE IF NOT EXISTS applications (')
        end = schema.index(';', start) + 1
        statement = schema[start:end].replace('IF NOT EXISTS applications', 'applications_guest')
        db.execute('BEGIN IMMEDIATE')
        db.execute(statement)
        names = ','.join(columns)
        db.execute(f'INSERT INTO applications_guest ({names}) SELECT {names} FROM applications')
        db.execute('DROP TABLE applications')
        db.execute('ALTER TABLE applications_guest RENAME TO applications')
        db.execute('CREATE INDEX applications_user ON applications(user_id)')
        db.execute('''CREATE UNIQUE INDEX applications_no_duplicate
            ON applications(phone,pet_id,visit_date,visit_time)
            WHERE user_id IS NULL AND status IN ('new','confirmed')''')
        db.commit()

    def migrate_accounts(self, db):
        """Старая база: логины вместо почты, без потери id, хешей, заявок и сессий."""
        user_columns = {row['name'] for row in db.execute('PRAGMA table_info(users)')}
        application_columns = {row['name'] for row in db.execute('PRAGMA table_info(applications)')}
        message_columns = {row['name'] for row in db.execute('PRAGMA table_info(messages)')}
        if not any('email' in columns for columns in (user_columns, application_columns, message_columns)):
            return

        # До изменения схемы сохраняем полноценную восстанавливаемую копию SQLite.
        backups = self.path.parent / 'backups'
        backups.mkdir(exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        with sqlite3.connect(backups / f'before-logins-{timestamp}.sqlite3') as backup:
            db.backup(backup)

        db.execute('BEGIN IMMEDIATE')
        if 'email' in user_columns:
            used = set()
            for row in db.execute('SELECT id,email FROM users ORDER BY id').fetchall():
                local = row['email'].split('@', 1)[0].lower()
                base = re.sub(r'[^a-zа-яё0-9_.-]', '', local).lstrip('._-')[:40] or f'user-{row["id"]}'
                candidate, number = base, 1
                while candidate in used:
                    suffix = f'-{row["id"]}' + (f'-{number}' if number > 1 else '')
                    candidate = base[:40-len(suffix)] + suffix
                    number += 1
                db.execute('UPDATE users SET email=? WHERE id=?', (candidate, row['id']))
                used.add(candidate)
            db.execute('ALTER TABLE users RENAME COLUMN email TO login')
        if 'email' in application_columns:
            db.execute('ALTER TABLE applications DROP COLUMN email')
        if 'email' in message_columns:
            db.execute('ALTER TABLE messages DROP COLUMN email')
        db.commit()

    def has_admin(self):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM users WHERE role='admin' LIMIT 1").fetchone() is not None
