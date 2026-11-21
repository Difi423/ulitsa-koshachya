"""Настройки production, HTTPS, проверка готовности, резервные копии и импорт."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend.app import create_app
from backend.config import Settings, origin
from backend.database import Database, ROOT
from backend.security import passwords
from manage import admin_from_env, backup_database, check_backup, restore_database


class ConfigurationTests(unittest.TestCase):
    def test_environment_controls_database_port_and_proxy(self):
        settings = Settings.from_env({'SHELTER_DB':'custom/db.sqlite3', 'SHELTER_PORT':'9000',
                    'PORT':'9100', 'SHELTER_HOST':'0.0.0.0', 'SHELTER_TRUSTED_PROXIES':'127.0.0.1'})
        self.assertEqual(settings.database, Path('custom/db.sqlite3'))
        self.assertEqual(settings.port, 9100)
        self.assertEqual(settings.trusted_proxies, '127.0.0.1')
        self.assertFalse(settings.secure_cookies)

    def test_production_requires_https_secure_cookie_and_known_hosts(self):
        for extra in [{}, {'SHELTER_PUBLIC_ORIGIN':'http://cats.example.org'},
                      {'SHELTER_PUBLIC_ORIGIN':'https://cats.example.org','SHELTER_SECURE_COOKIES':'0'},
                      {'SHELTER_PUBLIC_ORIGIN':'https://cats.example.org','SHELTER_ALLOWED_HOSTS':'*'}]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                Settings.from_env({'SHELTER_ENV':'production', **extra})
        settings = Settings.from_env({'SHELTER_ENV':'production','SHELTER_PUBLIC_ORIGIN':'https://cats.example.org'})
        self.assertTrue(settings.secure_cookies)
        self.assertFalse(settings.api_docs)
        self.assertIn('cats.example.org', settings.allowed_hosts)

    def test_origin_is_normalized_and_invalid_values_rejected(self):
        self.assertEqual(origin('https://CATS.example.org:443/'), 'https://cats.example.org')
        self.assertEqual(origin('http://[::1]:8000/'), 'http://[::1]:8000')
        for value in ['null','https://cats.example.org/path','https://u:p@cats.example.org',
                      'https://cats.example.org?x=1','https://cats.example.org#x', 'file:///tmp/x']:
            with self.subTest(value=value), self.assertRaises(ValueError): origin(value)
        for settings in [{'SHELTER_SECURE_COOKIES':'false'}, {'SHELTER_PORT':'0'},
                         {'SHELTER_LOG_LEVEL':'unknown'}, {'SHELTER_ENV':'other'}]:
            with self.subTest(settings=settings), self.assertRaises(ValueError): Settings.from_env(settings)


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/'runtime/shelter.sqlite3'
        self.settings = Settings.from_env({'SHELTER_ENV':'production',
                         'SHELTER_PUBLIC_ORIGIN':'https://cats.example.org','SHELTER_DB':str(self.path)})
        self.app = create_app(settings=self.settings)
        self.client = TestClient(self.app, base_url='https://cats.example.org')
        self.client.__enter__()
        with self.app.state.database.connect() as db:
            db.execute("INSERT INTO users(name,login,password_hash,role) VALUES (?,?,?,'admin')",
                       ('Куратор','curator',passwords.hash('1')))

    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.temp.cleanup()

    def test_https_origin_login_secure_cookie_and_csrf(self):
        response = self.client.post('/api/auth/login',json={'login':'curator','password':'1'},
                                    headers={'Origin':'https://cats.example.org:443'})
        self.assertEqual(response.status_code,200,response.text)
        cookie = response.headers['set-cookie']
        for attribute in ['Secure','HttpOnly','SameSite=lax']: self.assertIn(attribute,cookie)
        self.assertEqual(self.client.get('/api/admin/applications').status_code,200)
        self.assertEqual(self.client.post('/api/auth/logout',json={}).status_code,403)
        csrf = response.json()['csrfToken']
        self.assertEqual(self.client.post('/api/auth/logout',json={},headers={'X-CSRF-Token':csrf}).status_code,200)

    def test_host_and_foreign_origin_rejected(self):
        response = self.client.get('/api/pets',headers={'Host':'attacker.invalid'})
        self.assertEqual(response.status_code,400)
        for value in ['https://attacker.invalid','http://cats.example.org','null']:
            response = self.client.post('/api/messages',json={},headers={'Origin':value})
            self.assertEqual(response.status_code,403)

    def test_health_does_not_disclose_paths_and_docs_disabled(self):
        response = self.client.get('/api/health')
        self.assertEqual(response.json(),{'status':'ok'})
        self.assertNotIn(str(self.path),response.text)
        self.assertEqual(self.client.get('/api/docs').status_code,404)
        self.assertEqual(self.client.get('/api/openapi.json').status_code,404)
        with patch.object(self.app.state.database,'connect',side_effect=sqlite3.OperationalError('private path')):
            response = self.client.get('/api/health')
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.json(),{'status':'unavailable'})


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.database = Database(Path(self.temp.name)/'data/shelter.sqlite3')
        self.database.initialize()

    def tearDown(self): self.temp.cleanup()

    def name(self, database=None):
        with (database or self.database).connect() as db:
            return db.execute('SELECT name FROM pets WHERE id=1').fetchone()[0]

    def test_consistent_backup_and_restore_preserve_previous_state(self):
        original = self.name()
        copy = backup_database(self.database)
        self.assertEqual(check_backup(copy),copy.resolve())
        with self.database.connect() as db: db.execute("UPDATE pets SET name='Изменено' WHERE id=1")
        with self.assertRaises(ValueError): restore_database(self.database,copy)
        self.assertEqual(self.name(),'Изменено')
        previous = restore_database(self.database,copy,confirmed=True)
        self.assertEqual(self.name(),original)
        self.assertEqual(self.name(Database(previous)),'Изменено')

    def test_import_into_new_volume_initializes_legacy_schema(self):
        with self.database.connect() as db:
            db.execute('DROP INDEX applications_no_duplicate')
            db.execute('DROP INDEX applications_user')
            db.execute('DROP TABLE applications')
            legacy = (ROOT/'tests/fixtures/schema-v2.sql').read_text()
            start = legacy.index('CREATE TABLE IF NOT EXISTS applications (')
            db.executescript(legacy[start:legacy.index('CREATE TABLE IF NOT EXISTS sessions',start)])
            db.execute('PRAGMA user_version=2')
        copy = backup_database(self.database)
        target = Database(Path(self.temp.name)/'new-volume/shelter.sqlite3')
        self.assertIsNone(restore_database(target,copy,confirmed=True))
        with target.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM pets').fetchone()[0],15)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],4)
            self.assertFalse(next(row for row in db.execute('PRAGMA table_info(applications)')
                                 if row['name']=='user_id')['notnull'])

    def test_invalid_copy_never_overwrites_database(self):
        invalid = Path(self.temp.name)/'invalid.sqlite3'
        invalid.write_bytes(b'not sqlite')
        with self.assertRaises(sqlite3.DatabaseError): restore_database(self.database,invalid,confirmed=True)
        self.assertEqual(self.name(),'Персик')
        with sqlite3.connect(Path(self.temp.name)/'empty.sqlite3') as db:
            pass
        with self.assertRaises(ValueError): check_backup(Path(self.temp.name)/'empty.sqlite3')
        with self.assertRaises(ValueError): restore_database(self.database,self.database.path,confirmed=True)
        with self.assertRaises(ValueError): backup_database(Database(Path(self.temp.name)/'missing.sqlite3'))

    def test_unusable_schema_is_migrated_before_overwriting(self):
        copy = backup_database(self.database)
        with sqlite3.connect(copy) as db: db.execute('ALTER TABLE pets RENAME COLUMN name TO bad_column')
        with self.assertRaises(ValueError): restore_database(self.database,copy,confirmed=True)
        self.assertEqual(self.name(),'Персик')

    def test_admin_from_env_hashes_password_and_never_resets_existing_login(self):
        values={'SHELTER_ADMIN_NAME':'Куратор','SHELTER_ADMIN_LOGIN':'ADMIN','SHELTER_ADMIN_PASSWORD':'1'}
        admin_from_env(self.database,values)
        with self.database.connect() as db:
            user = db.execute('SELECT * FROM users').fetchone()
            self.assertEqual(user['login'],'admin')
            self.assertEqual(user['role'],'admin')
            self.assertTrue(passwords.verify('1',user['password_hash']))
        with self.assertRaises(ValueError): admin_from_env(self.database,values)
        with self.assertRaises(ValueError): admin_from_env(self.database,{})

    def test_cli_does_not_print_invalid_password(self):
        secret = 'hidden-password-' * 12
        environment = dict(os.environ, SHELTER_DB=str(self.database.path), SHELTER_ADMIN_LOGIN='new-admin',
                           SHELTER_ADMIN_NAME='Куратор', SHELTER_ADMIN_PASSWORD=secret)
        result = subprocess.run([sys.executable, str(ROOT/'manage.py'), 'create-admin', '--from-env'],
                                env=environment, capture_output=True, text=True)
        self.assertEqual(result.returncode,1)
        self.assertNotIn(secret,result.stdout+result.stderr)


if __name__=='__main__': unittest.main()
