"""Запуск: python -m unittest discover -s tests -v (requirements-dev.txt)."""
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
import time
import json
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient
from backend.app import create_app
from backend.database import Database, ROOT, INSERT_PET, pet_values
from backend.models import MOSCOW, AdminAccount
from backend.security import COOKIE_NAME, passwords, token_hash


def visit_day():
    day = datetime.now(MOSCOW).date() + timedelta(days=2)
    if day.weekday() == 0:
        day += timedelta(days=1)
    return day.isoformat()


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / 'test.sqlite3'
        self.app = create_app(self.path, secure_cookies=False)
        self.client = TestClient(self.app)
        self.client.__enter__()
        with self.app.state.database.connect() as db:
            db.execute("INSERT INTO users(name,login,password_hash,role) VALUES (?,?,?,'admin')",
                       ('Куратор', 'curator', passwords.hash('AdminTest123!')))

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def admin(self):
        response = self.client.post('/api/auth/login', json={
            'login': 'curator', 'password': 'AdminTest123!'})
        self.assertEqual(response.status_code, 200, response.text)
        self.client.headers['X-CSRF-Token'] = response.json()['csrfToken']
        return response

    def application(self):
        return {'pet_id': 1, 'visitor_name': 'Посетитель', 'phone': '+7 (900) 000-00-00',
                'visit_date': visit_day(), 'visit_time': '14-16',
                'comment': 'Тестовая заявка без реальных личных данных.', 'confirmed': True}

    def test_fifteen_pets_and_single_item(self):
        self.assertEqual(len(self.client.get('/api/pets').json()), 15)
        self.assertEqual(self.client.get('/api/pets/13').json()['slug'], 'snezhka')
        self.assertEqual(self.client.get('/api/pets/slug/luna').json()['id'], 2)
        self.assertEqual(self.client.get('/api/pets/9999').status_code, 404)

    def test_guest_application_without_account_and_minimal_receipt(self):
        response = self.client.post('/api/applications', json=self.application())
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(set(response.json()), {'id', 'status'})
        self.assertEqual(response.json()['status'], 'new')
        self.assertIsNone(self.client.cookies.get(COOKIE_NAME))
        with self.app.state.database.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM users').fetchone()[0], 1)
            item = db.execute('SELECT * FROM applications').fetchone()
            self.assertIsNone(item['user_id'])
            self.assertEqual(item['phone'], '+79000000000')
            self.assertEqual(item['visitor_name'], 'Посетитель')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_registration_and_public_application_history_removed(self):
        response = self.client.post('/api/auth/register', json={
            'name': 'Посетитель', 'login': 'visitor', 'password': '1', 'role': 'admin'})
        self.assertEqual(response.status_code, 404)
        item = self.client.post('/api/applications', json=self.application()).json()
        self.assertEqual(self.client.get('/api/applications').status_code, 404)
        self.assertEqual(self.client.get(f"/api/applications/{item['id']}").status_code, 404)
        self.assertEqual(self.client.patch(f"/api/applications/{item['id']}/cancel", json={}).status_code, 404)
        with self.app.state.database.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM users').fetchone()[0], 1)

    def test_guest_and_old_visitor_session_cannot_use_admin(self):
        for url in ['/api/admin/pets', '/api/admin/applications', '/api/admin/messages', '/api/admin/photos']:
            self.assertEqual(self.client.get(url).status_code, 401)
        self.assertEqual(self.client.delete('/api/admin/pets/1').status_code, 401)
        with self.app.state.database.connect() as db:
            cursor = db.execute("INSERT INTO users(name,login,password_hash,role) VALUES (?,?,?,'user')",
                                ('Посетитель', 'visitor', passwords.hash('1')))
            db.execute('INSERT INTO sessions VALUES (?,?,?,?)',
                       (token_hash('old-visitor'), cursor.lastrowid, 'visitor-csrf', int(time.time()) + 1000))
        self.assertEqual(self.client.post('/api/auth/login', json={'login':'visitor','password':'1'}).status_code, 401)
        self.client.cookies.set(COOKIE_NAME, 'old-visitor')
        self.assertIsNone(self.client.get('/api/auth/me').json()['user'])
        self.assertEqual(self.client.get('/api/admin/applications').status_code, 401)
        self.assertEqual(self.client.post('/api/applications', json=self.application()).status_code, 201)

    def test_duplicate_normalized_phone_and_different_pet(self):
        self.assertEqual(self.client.post('/api/applications', json=self.application()).status_code, 201)
        duplicate = {**self.application(), 'phone':'8 900 000 00 00', 'visitor_name':'Другое имя'}
        self.assertEqual(self.client.post('/api/applications', json=duplicate).status_code, 409)
        self.assertEqual(self.client.post('/api/applications', json={**duplicate,'pet_id':2}).status_code, 201)
        self.assertEqual(self.client.post('/api/applications', json={**duplicate,'visit_time':'16-18'}).status_code, 201)

    def test_guest_submission_persists_after_restart_and_admin_reads_it(self):
        self.client.post('/api/applications', json=self.application())
        with TestClient(create_app(self.path)) as restarted:
            login = restarted.post('/api/auth/login', json={'login':'curator','password':'AdminTest123!'})
            self.assertEqual(login.status_code, 200)
            items = restarted.get('/api/admin/applications').json()
            self.assertEqual(len(items), 1)
            self.assertIsNone(items[0]['user_id'])
            self.assertEqual(items[0]['visitor_name'], 'Посетитель')
            self.assertEqual(items[0]['phone'], '+79000000000')

    def test_admin_cookie_does_not_attach_identity_to_public_forms(self):
        self.admin()
        self.client.headers.pop('X-CSRF-Token')
        response = self.client.post('/api/applications', json=self.application())
        self.assertEqual(response.status_code, 201, response.text)
        response = self.client.post('/api/messages', json={'name':'Гость','topic':'question','message':'Тестовое сообщение.'})
        self.assertEqual(response.status_code, 201, response.text)
        with self.app.state.database.connect() as db:
            self.assertIsNone(db.execute('SELECT user_id FROM applications').fetchone()[0])
            self.assertIsNone(db.execute('SELECT user_id FROM messages').fetchone()[0])
        self.assertEqual(self.client.delete('/api/admin/pets/1').status_code, 403)

    def test_server_validation_and_pet_status(self):
        changes = [{'phone':'abc'}, {'visit_date':'2000-01-01'}, {'visit_date':'2026-02-30'},
                   {'visit_time':'99-99'}, {'confirmed':False}, {'confirmed':1}, {'user_id':1},
                   {'email':'unused@example.test'}, {'status':'confirmed'}, {'admin_note':'Подмена'}]
        for change in changes:
            with self.subTest(change=change):
                self.assertEqual(self.client.post('/api/applications', json={**self.application(),**change}).status_code, 422)
        with self.app.state.database.connect() as db:
            db.execute('UPDATE pets SET status=? WHERE id=?', ('adopted',1))
        self.assertEqual(self.client.post('/api/applications', json=self.application()).status_code, 409)
        self.assertEqual(self.client.post('/api/applications', json={**self.application(),'pet_id':9999}).status_code, 409)

    def test_admin_tracks_guest_status_and_private_note(self):
        created = self.client.post('/api/applications', json=self.application()).json()
        self.admin()
        url = f"/api/admin/applications/{created['id']}"
        response = self.client.patch(url, json={'status':'confirmed','admin_note':'Договорились о времени.'})
        self.assertEqual(response.status_code, 200)
        item = self.client.get('/api/admin/applications').json()[0]
        self.assertEqual(item['status'], 'confirmed')
        self.assertEqual(item['admin_note'], 'Договорились о времени.')
        self.assertEqual(self.client.patch(url, json={'status':'new'}).status_code, 409)
        self.assertEqual(self.client.patch(url, json={'status':'completed'}).status_code, 200)
        self.assertEqual(self.client.patch(url, json={'status':'confirmed'}).status_code, 409)
        self.client.post('/api/auth/logout', json={})
        self.assertEqual(self.client.get('/api/admin/applications').status_code, 401)
        self.assertEqual(self.client.get('/api/applications').status_code, 404)

    def test_cancelled_request_can_be_submitted_again(self):
        created = self.client.post('/api/applications', json=self.application()).json()
        self.admin()
        self.client.patch(f"/api/admin/applications/{created['id']}", json={'status':'cancelled'})
        self.client.post('/api/auth/logout', json={})
        self.assertEqual(self.client.post('/api/applications', json=self.application()).status_code, 201)

    def test_admin_password_hash_and_session_are_not_plaintext(self):
        response = self.admin()
        self.assertNotIn('password_hash', response.json()['user'])
        self.assertNotIn('email', response.json()['user'])
        token = self.client.cookies.get(COOKIE_NAME)
        with self.app.state.database.connect() as db:
            row = db.execute('SELECT password_hash FROM users WHERE login=?', ('curator',)).fetchone()
            self.assertTrue(row['password_hash'].startswith('$argon2id$'))
            self.assertTrue(passwords.verify('AdminTest123!', row['password_hash']))
            stored = db.execute('SELECT token_hash FROM sessions').fetchone()[0]
            self.assertEqual(stored, token_hash(token))
            self.assertNotEqual(stored, token)
        self.assertTrue(any(cookie.name == COOKIE_NAME and cookie.has_nonstandard_attr('HttpOnly')
                            for cookie in self.client.cookies.jar))

    def test_login_logout_and_expiry(self):
        self.assertEqual(self.client.post('/api/auth/login',json={'login':'missing','password':'1'}).status_code,401)
        self.admin()
        token = self.client.cookies.get(COOKIE_NAME)
        self.assertEqual(self.client.post('/api/auth/logout',json={}).status_code,200)
        self.client.cookies.set(COOKIE_NAME,token)
        self.assertIsNone(self.client.get('/api/auth/me').json()['user'])
        self.assertEqual(self.client.get('/api/admin/pets').status_code,401)
        self.admin()
        with self.app.state.database.connect() as db: db.execute('UPDATE sessions SET expires_at=0')
        self.assertIsNone(self.client.get('/api/auth/me').json()['user'])
        self.assertEqual(self.client.get('/api/admin/pets').status_code,401)

    def test_admin_csrf_and_public_origin_json_limits(self):
        self.admin()
        self.assertEqual(self.client.delete('/api/admin/pets/1',headers={'X-CSRF-Token':''}).status_code,403)
        self.assertEqual(self.client.post('/api/auth/logout',json={},headers={'Origin':'https://other.invalid'}).status_code,403)
        self.client.post('/api/auth/logout',json={})
        self.assertEqual(self.client.post('/api/applications',json=self.application(),headers={'Origin':'https://other.invalid'}).status_code,403)
        self.assertEqual(self.client.post('/api/messages',content='{}',headers={'Content-Type':'text/plain'}).status_code,415)
        self.assertEqual(self.client.post('/api/messages',content='x'*70000,headers={'Content-Type':'application/json'}).status_code,413)

    def test_admin_create_edit_archive_restore_and_sql_literal(self):
        self.admin()
        pet = self.client.get('/api/pets/1').json()
        keys = ['slug','name','ageMonths','sex','temperament','trait','color','short','story','home','care','image','alt','featured','status']
        body = {key:pet[key] for key in keys}
        body.update(slug='test-pet',name='Тестик',short="Строка '); DROP TABLE pets; -- остаётся обычным текстом.")
        response = self.client.post('/api/admin/pets',json=body)
        self.assertEqual(response.status_code,201,response.text)
        identifier = response.json()['id']
        self.assertEqual(len(self.client.get('/api/pets').json()),16)
        body['name'] = 'Новое имя'
        self.assertEqual(self.client.put(f'/api/admin/pets/{identifier}',json=body).status_code,200)
        self.assertEqual(self.client.get(f'/api/pets/{identifier}').json()['name'],'Новое имя')
        self.assertEqual(self.client.delete(f'/api/admin/pets/{identifier}').status_code,200)
        self.assertEqual(self.client.get(f'/api/pets/{identifier}').status_code,404)
        self.assertEqual(len(self.client.get('/api/admin/pets').json()),16)
        self.assertEqual(self.client.put(f'/api/admin/pets/{identifier}',json=body).status_code,200)
        self.assertEqual(self.client.post('/api/admin/pets',json=body).status_code,409)
        self.assertEqual(self.client.put(f'/api/admin/pets/{identifier}',json={**body,'image':'../data/shelter.sqlite3'}).status_code,422)

    def test_messages_saved_and_status_updated(self):
        response = self.client.post('/api/messages',json={'name':'Гость','topic':'question','message':'Тестовое сообщение без личных данных.'})
        self.assertEqual(response.status_code,201)
        self.admin()
        items = self.client.get('/api/admin/messages').json()
        self.assertEqual(len(items),1)
        self.assertEqual(self.client.patch(f"/api/admin/messages/{items[0]['id']}",json={'status':'read'}).status_code,200)
        self.assertEqual(self.client.get('/api/admin/messages').json()[0]['status'],'read')

    def test_database_not_public_and_legacy_bookmark_redirect(self):
        for path in ['/data/shelter.sqlite3','/backend/schema.sql','/start.py','/api/no-such-route']:
            self.assertEqual(self.client.get(path).status_code,404,path)
        for path in ['/','/catalog.html','/application.html','/pet.html?id=13','/admin-login.html','/admin.html']:
            self.assertEqual(self.client.get(path).status_code,200,path)
        response = self.client.get('/account.html',follow_redirects=False)
        self.assertEqual(response.status_code,302)
        self.assertEqual(response.headers['location'],'/admin-login.html')

    def test_cli_admin_accepts_one_character_password_and_normalizes_login(self):
        from unittest.mock import patch
        from start import create_admin
        with patch('builtins.input',side_effect=['Анна','МАША']), patch('getpass.getpass',return_value='1'):
            create_admin(self.app.state.database)
        response = self.client.post('/api/auth/login',json={'login':'МАША','password':'1'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['user']['login'],'маша')
        self.client.headers['X-CSRF-Token'] = response.json()['csrfToken']
        self.assertEqual(self.client.post('/api/auth/login',json={'login':'маша','password':''}).status_code,422)
        self.assertEqual(self.client.post('/api/auth/login',json={'login':'curator','password':'1','role':'admin'}).status_code,422)
        self.assertEqual(AdminAccount(name='Тестер',login='tester',password='  1  ').password,'  1  ')


def make_legacy_database(path):
    database=Database(path)
    with database.connect() as db:
        db.executescript((Path(__file__).parent/'fixtures/schema-v1.sql').read_text())
        for pet in json.loads((ROOT/'backend/seed/pets.json').read_text()):
            db.execute(INSERT_PET,pet_values(pet))
        hashed=passwords.hash('LegacyPass123!')
        for email,role in [('alpha@one.test','admin'),('ALPHA@two.test','user'),('猫@three.test','user')]:
            db.execute('INSERT INTO users(name,email,password_hash,role) VALUES (?,?,?,?)',('Участник',email,hashed,role))
        db.execute('''INSERT INTO applications(user_id,pet_id,visitor_name,phone,email,visit_date,visit_time,comment)
            VALUES (?,?,?,?,?,?,?,?)''',(1,1,'Участник','+79000000000','alpha@one.test',visit_day(),'14-16','Сохранить историю.'))
        db.execute('INSERT INTO messages(user_id,name,email,topic,message) VALUES (?,?,?,?,?)',
                   (1,'Участник','alpha@one.test','question','Сохранить сообщение.'))
        db.execute('INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at) VALUES (?,?,?,?)',
                   (token_hash('legacy-session'),1,'legacy-csrf',int(time.time())+3600))
    return database,hashed


class MigrationTests(unittest.TestCase):
    def make_v2_database(self, path):
        database = Database(path)
        with database.connect() as db:
            db.executescript((Path(__file__).parent/'fixtures/schema-v2.sql').read_text())
            for pet in json.loads((ROOT/'backend/seed/pets.json').read_text()):
                db.execute(INSERT_PET, pet_values(pet))
            hashed = passwords.hash('1')
            for name, role in [('Куратор', 'admin'), ('Посетитель', 'user')]:
                db.execute('INSERT INTO users(name,login,password_hash,role) VALUES (?,?,?,?)',
                           (name, role, hashed, role))
            # В старой версии два аккаунта могли оставить заявки с одним телефоном.
            for user_id in (1, 2):
                db.execute('''INSERT INTO applications
                    (id,user_id,pet_id,visitor_name,phone,visit_date,visit_time,status,admin_note)
                    VALUES (?,?,?,?,?,?,?,?,?)''',
                    (user_id + 20, user_id, 1, 'Посетитель', '+79000000000', visit_day(),
                     '14-16', 'confirmed', 'Сохранить заметку.'))
            db.execute('PRAGMA user_version=2')
        return database, hashed

    def test_v2_guest_migration_preserves_history_and_is_idempotent(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)/'v2.sqlite3'
            database, hashed = self.make_v2_database(path)
            database.initialize()
            database.initialize()
            with database.connect() as db:
                rows = db.execute('SELECT * FROM applications ORDER BY id').fetchall()
                self.assertEqual([row['id'] for row in rows], [21, 22])
                self.assertEqual([row['user_id'] for row in rows], [1, 2])
                self.assertEqual(rows[0]['admin_note'], 'Сохранить заметку.')
                self.assertEqual(db.execute('SELECT password_hash FROM users WHERE id=1').fetchone()[0], hashed)
                self.assertFalse(next(row for row in db.execute('PRAGMA table_info(applications)')
                                      if row['name']=='user_id')['notnull'])
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 4)
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            copies = list((Path(folder)/'backups').glob('before-guest-applications-*.sqlite3'))
            self.assertEqual(len(copies), 1)
            with sqlite3.connect(copies[0]) as backup:
                self.assertEqual(backup.execute('SELECT COUNT(*) FROM applications').fetchone()[0], 2)
                self.assertEqual(backup.execute('PRAGMA user_version').fetchone()[0], 2)
            with TestClient(create_app(path)) as client:
                body = {'pet_id':1, 'visitor_name':'Посетитель', 'phone':'8 (900) 000-00-00',
                        'visit_date':visit_day(), 'visit_time':'14-16', 'confirmed':True}
                self.assertEqual(client.post('/api/applications',json=body).status_code, 409)
                self.assertEqual(client.post('/api/applications',json={**body,'pet_id':2,'visit_time':'16-18'}).status_code, 201)
                client.post('/api/auth/login',json={'login':'admin','password':'1'})
                self.assertEqual(len(client.get('/api/admin/applications').json()), 3)

    def test_guest_migration_failure_rolls_back_and_retains_backup(self):
        with TemporaryDirectory() as folder:
            database, _ = self.make_v2_database(Path(folder)/'v2.sqlite3')
            with self.assertRaises(sqlite3.DatabaseError):
                with database.connect() as db:
                    db.set_authorizer(lambda action, *args: sqlite3.SQLITE_DENY
                                      if action == sqlite3.SQLITE_ALTER_TABLE else sqlite3.SQLITE_OK)
                    database.migrate_guest_applications(db)
            with database.connect() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM applications').fetchone()[0], 2)
                self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='applications_guest'").fetchone())
                self.assertTrue(next(row for row in db.execute('PRAGMA table_info(applications)')
                                     if row['name']=='user_id')['notnull'])
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(len(list((Path(folder)/'backups').glob('*.sqlite3'))), 1)

    def test_legacy_accounts_applications_sessions_and_backup(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'legacy.sqlite3'
            database,hashed=make_legacy_database(path)
            with TestClient(create_app(path)) as client:
                client.cookies.set(COOKIE_NAME,'legacy-session')
                current=client.get('/api/auth/me').json()
                self.assertEqual(current['user']['login'],'alpha')
                self.assertEqual(current['user']['role'],'admin')
                applications=client.get('/api/admin/applications').json()
                self.assertEqual(len(applications),1)
                self.assertEqual(applications[0]['comment'],'Сохранить историю.')
                self.assertNotIn('email',applications[0])
                client.headers['X-CSRF-Token']='legacy-csrf'
                self.assertEqual(client.post('/api/auth/login',json={'login':'alpha','password':'LegacyPass123!'}).status_code,200)
            database.initialize()
            with database.connect() as db:
                self.assertEqual([row['login'] for row in db.execute('SELECT login FROM users ORDER BY id')],['alpha','alpha-2','user-3'])
                self.assertEqual(db.execute('SELECT password_hash FROM users WHERE id=?',(1,)).fetchone()[0],hashed)
                self.assertEqual(db.execute('SELECT message FROM messages').fetchone()[0],'Сохранить сообщение.')
                for table in ['users','applications','messages']:
                    self.assertNotIn('email',{row['name'] for row in db.execute('PRAGMA table_info('+table+')')})
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],4)
            copies=list((Path(folder)/'backups').glob('before-logins-*.sqlite3'))
            self.assertEqual(len(copies),1)
            with sqlite3.connect(copies[0]) as backup:
                self.assertEqual(backup.execute('SELECT COUNT(*) FROM users').fetchone()[0],3)
                self.assertEqual(backup.execute('SELECT email FROM users WHERE id=1').fetchone()[0],'alpha@one.test')

    def test_failed_migration_rolls_back_and_keeps_backup(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'legacy.sqlite3'
            database,_=make_legacy_database(path)
            with database.connect() as db:
                db.execute('CREATE INDEX legacy_email_index ON messages(email)')
            with self.assertRaises(sqlite3.OperationalError): database.initialize()
            with database.connect() as db:
                self.assertIn('email',{row['name'] for row in db.execute('PRAGMA table_info(users)')})
                self.assertEqual(db.execute('SELECT email FROM users WHERE id=1').fetchone()[0],'alpha@one.test')
                self.assertEqual(db.execute('SELECT COUNT(*) FROM applications').fetchone()[0],1)
            self.assertEqual(len(list((Path(folder)/'backups').glob('*.sqlite3'))),1)


if __name__=='__main__': unittest.main()
