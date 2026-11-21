"""Проверяем новые функции на настоящих SQLite и HTTP, без рабочей базы."""
from concurrent.futures import ThreadPoolExecutor
import csv
from dataclasses import replace
from datetime import datetime,timedelta
from io import BytesIO,StringIO
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
import zipfile

from fastapi.testclient import TestClient
from PIL import Image
from backend.app import create_app
from backend.config import Settings
from backend.database import Database,INSERT_PET,ROOT,pet_values
from backend.models import MOSCOW
from backend.security import passwords
from manage import backup_project,restore_project,check_backup,file_hash


def day():
    value=datetime.now(MOSCOW).date()+timedelta(days=2)
    if value.weekday()==0:value+=timedelta(days=1)
    return value.isoformat()


def png(color='orange'):
    stream=BytesIO();Image.new('RGB',(48,32),color).save(stream,'PNG')
    return stream.getvalue()


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.path=Path(self.temp.name)/'data/shelter.sqlite3'
        self.app=create_app(self.path)
        self.client=TestClient(self.app);self.client.__enter__()
        with self.app.state.database.connect() as db:
            db.execute("INSERT INTO users(name,login,password_hash,role) VALUES (?,?,?,'admin')",('Куратор','admin',passwords.hash('1')))

    def tearDown(self):
        self.client.__exit__(None,None,None);self.temp.cleanup()

    def admin(self):
        data=self.client.post('/api/auth/login',json={'login':'admin','password':'1'}).json()
        self.client.headers['X-CSRF-Token']=data['csrfToken']

    def request_body(self,phone='+79000000000'):
        return {'pet_id':1,'visitor_name':'Посетитель','phone':phone,'visit_date':day(),'visit_time':'14-16','confirmed':True}

    def application(self,phone='+79000000000'):
        response=self.client.post('/api/applications',json=self.request_body(phone))
        self.assertEqual(response.status_code,201,response.text)
        return response.json()['id']

    def pet_body(self):
        pet=self.client.get('/api/pets/1').json()
        keys=['slug','name','ageMonths','sex','temperament','trait','color','short','story','home','care','image','alt','featured','status']
        return {key:pet[key] for key in keys}

    def upload(self):
        response=self.client.post('/api/admin/uploads',files=[('files',('../../a.png',png(),'image/png')),('files',('b.jpg',png('blue'),'image/jpeg'))])
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def test_upload_requires_admin_csrf_and_actual_images(self):
        self.assertEqual(self.client.post('/api/admin/uploads',files={'files':('a.png',png())}).status_code,401)
        self.admin()
        self.assertEqual(self.client.post('/api/admin/uploads',files={'files':('a.png',png())},headers={'X-CSRF-Token':''}).status_code,403)
        self.assertEqual(self.client.post('/api/admin/uploads',json={}).status_code,415)
        response=self.client.post('/api/admin/uploads',files={'files':('evil.png',b'<svg onload="alert(1)"></svg>','image/png')})
        self.assertEqual(response.status_code,422)
        self.assertEqual(list(self.app.state.media_directory.glob('*.webp')),[])

    def test_upload_normalizes_image_and_gallery_cover_survives_restart(self):
        self.admin();photos=self.upload()
        for item in photos:
            self.assertRegex(item['image'],r'^media/[a-f0-9]{32}\.webp$')
            with Image.open(self.app.state.media_directory/item['image'].split('/')[-1]) as image:
                self.assertEqual(image.format,'WEBP');self.assertEqual(image.size,(48,32))
            self.assertEqual(self.client.get('/'+item['image']).status_code,200)
        body={**self.pet_body(),'image':photos[1]['image'],'alt':'Синее тестовое фото',
              'photos':[{'image':item['image'],'alt':'Тестовая фотография'} for item in photos]}
        result=self.client.put('/api/admin/pets/1',json=body)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['image'],photos[1]['image'])
        self.assertEqual([item['image'] for item in result.json()['photos']],[item['image'] for item in photos])
        with TestClient(create_app(self.path)) as restarted:
            self.assertEqual(restarted.get('/api/pets/1').json()['image'],photos[1]['image'])
            self.assertEqual(restarted.get('/'+photos[1]['image']).status_code,200)

    def test_upload_limits_and_failed_batch_leave_no_partial_photos(self):
        self.admin()
        self.assertEqual(self.client.post('/api/admin/uploads',files={'files':('x.png',b'x'*(6*1024*1024+1))}).status_code,413)
        self.assertEqual(self.client.post('/api/admin/uploads',files=[('files',('x.png',png()))]*9).status_code,422)
        response=self.client.post('/api/admin/uploads',files=[('files',('good.png',png())),('files',('bad.png',b'bad'))])
        self.assertEqual(response.status_code,422)
        self.assertFalse(list(self.app.state.media_directory.glob('*.webp')))
        self.assertEqual(self.client.post('/api/messages',content=iter([b' '*40000,b' '*40000]),headers={'Content-Type':'application/json'}).status_code,413)

    def test_missing_or_duplicate_gallery_photo_cannot_overwrite_pet(self):
        self.admin();body=self.pet_body()
        self.assertEqual(self.client.put('/api/admin/pets/1',json={**body,'image':'media/'+'a'*32+'.webp'}).status_code,422)
        duplicate=[{'image':body['image'],'alt':'Фото'}]*2
        self.assertEqual(self.client.put('/api/admin/pets/1',json={**body,'photos':duplicate}).status_code,422)
        self.assertEqual(self.client.get('/api/pets/1').json()['image'],body['image'])

    def test_availability_tracks_confirmations_and_never_exposes_contacts(self):
        identifier=self.application()
        url=f'/api/availability?date={day()}&pet_id=1'
        slots=self.client.get(url).json()['slots']
        self.assertTrue(next(item for item in slots if item['value']=='14-16')['available'])
        self.admin()
        self.assertEqual(self.client.patch(f'/api/admin/applications/{identifier}',json={'status':'confirmed'}).status_code,200)
        response=self.client.get(url)
        self.assertFalse(next(item for item in response.json()['slots'] if item['value']=='14-16')['available'])
        self.assertNotIn('Посетитель',response.text);self.assertNotIn('+79000000000',response.text)
        self.assertEqual(self.client.post('/api/applications',json=self.request_body('+79000000001')).status_code,409)
        self.client.patch(f'/api/admin/applications/{identifier}',json={'status':'cancelled'})
        self.assertTrue(next(item for item in self.client.get(url).json()['slots'] if item['value']=='14-16')['available'])

    def test_two_simultaneous_confirmations_cannot_overbook(self):
        first=self.application();second=self.application('+79000000001');self.admin()
        def confirm(identifier):return self.client.patch(f'/api/admin/applications/{identifier}',json={'status':'confirmed'}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(confirm,[first,second]))
        self.assertEqual(sorted(results),[200,409])
        with self.app.state.database.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM applications WHERE status='confirmed'").fetchone()[0],1)

    def test_capacity_is_configurable(self):
        settings=replace(Settings.from_env(),slot_capacity=2)
        with TestClient(create_app(Path(self.temp.name)/'capacity.sqlite3',settings=settings)) as client:
            with client.app.state.database.connect() as db:
                db.execute("INSERT INTO users(name,login,password_hash,role) VALUES (?,?,?,'admin')",('Куратор','admin',passwords.hash('1')))
            ids=[]
            for phone in ['+79000000001','+79000000002','+79000000003']:
                ids.append(client.post('/api/applications',json=self.request_body(phone)).json()['id'])
            token=client.post('/api/auth/login',json={'login':'admin','password':'1'}).json()['csrfToken']
            results=[client.patch(f'/api/admin/applications/{identifier}',json={'status':'confirmed'},headers={'X-CSRF-Token':token}).status_code for identifier in ids]
            self.assertEqual(results,[200,200,409])

    def test_history_is_private_atomic_and_records_rescheduling(self):
        identifier=self.application();url=f'/api/admin/applications/{identifier}/history'
        self.assertEqual(self.client.get(url).status_code,401);self.admin()
        response=self.client.patch(f'/api/admin/applications/{identifier}',json={'status':'confirmed','admin_note':'Позвонили.','visit_time':'16-18'})
        self.assertEqual(response.status_code,200,response.text)
        events=self.client.get(url).json()
        self.assertEqual([item['kind'] for item in events],['created','updated'])
        event=events[-1]
        self.assertEqual(event['old_visit_time'],'14-16');self.assertEqual(event['new_visit_time'],'16-18')
        self.assertEqual(event['actor_name'],'Куратор');self.assertEqual(event['note'],'Позвонили.')
        self.client.patch(f'/api/admin/applications/{identifier}',json={'status':'confirmed','admin_note':'Позвонили.'})
        self.assertEqual(len(self.client.get(url).json()),2)
        self.client.patch(f'/api/admin/applications/{identifier}',json={'status':'completed','admin_note':'Встреча прошла.'})
        self.assertEqual(self.client.patch(f'/api/admin/applications/{identifier}',json={'status':'completed','visit_time':'12-14'}).status_code,409)
        self.assertEqual(len(self.client.get(url).json()),3)

    def test_calendar_and_date_validation(self):
        identifier=self.application()
        self.assertEqual(self.client.get('/api/admin/calendar').status_code,401);self.admin()
        response=self.client.get(f'/api/admin/calendar?from={day()}&to={day()}')
        self.assertEqual(response.json()['items'][0]['id'],identifier)
        self.assertEqual(self.client.get('/api/admin/calendar?from=2026-01-01&to=2027-01-01').status_code,422)
        self.assertEqual(self.client.get('/api/availability?date=20261104&pet_id=1').status_code,422)
        monday=datetime.now(MOSCOW).date()+timedelta(days=7)
        monday-=timedelta(days=monday.weekday())
        slots=self.client.get(f'/api/availability?date={monday.isoformat()}&pet_id=1').json()['slots']
        self.assertTrue(all(not item['available'] for item in slots))

    def test_adoption_story_and_date_are_public_and_old_update_preserves_them(self):
        self.admin();body={**self.pet_body(),'status':'adopted','adoptionStory':'Персик нашёл дом и любит спать на диване.'}
        response=self.client.put('/api/admin/pets/1',json=body)
        self.assertEqual(response.status_code,200,response.text)
        pet=response.json();self.assertEqual(pet['adoptedAt'],datetime.now(MOSCOW).date().isoformat())
        self.assertIn('нашёл дом',pet['adoptionStory'])
        self.client.put('/api/admin/pets/1',json={**self.pet_body(),'status':'adopted'})
        self.assertEqual(self.client.get('/api/pets/1').json()['adoptionStory'],body['adoptionStory'])

    def test_statistics_use_moscow_dates_and_csv_is_private_and_excel_safe(self):
        self.application();self.admin()
        with self.app.state.database.connect() as db:
            db.execute("UPDATE applications SET created_at='2026-11-03T22:30:00Z',comment='=HYPERLINK(1)',admin_note='+test'")
        url='/api/admin/statistics?from=2026-11-04&to=2026-11-04'
        data=self.client.get(url).json()
        self.assertEqual(data['totals']['all'],1);self.assertEqual(data['daily'],[{'date':'2026-11-04','count':1}])
        self.assertEqual(data['popular'][0]['name'],'Персик')
        response=self.client.get('/api/admin/applications.csv?from=2026-11-04&to=2026-11-04')
        self.assertTrue(response.content.startswith(b'\xef\xbb\xbf'))
        rows=list(csv.reader(StringIO(response.content.decode('utf-8-sig')),delimiter=';'))
        self.assertTrue(rows[1][7].startswith("'="));self.assertTrue(rows[1][8].startswith("'+"))
        self.assertEqual(rows[1][9],'2026-11-04 01:30')
        self.client.post('/api/auth/logout',json={})
        self.assertEqual(self.client.get(url).status_code,401)
        self.assertEqual(self.client.get('/api/admin/applications.csv').status_code,401)

    def test_full_backup_restores_uploaded_photos_and_database(self):
        self.admin();photos=self.upload()
        body={**self.pet_body(),'image':photos[0]['image'],'photos':[{'image':p['image'],'alt':'Фото питомца'} for p in photos]}
        self.client.put('/api/admin/pets/1',json=body)
        copy=backup_project(self.app.state.database,self.app.state.media_directory)
        target=Database(Path(self.temp.name)/'fresh/shelter.sqlite3');media=target.path.parent/'uploads'
        self.assertIsNone(restore_project(target,media,copy,confirmed=True))
        with TestClient(create_app(target.path)) as client:
            pet=client.get('/api/pets/1').json();self.assertEqual(len(pet['photos']),2)
            self.assertEqual(client.get('/'+photos[0]['image']).status_code,200)
        bad=Path(self.temp.name)/'bad.zip'
        with zipfile.ZipFile(bad,'w') as archive:
            archive.writestr('../outside',b'bad');archive.writestr('manifest.json','{}');archive.writestr('shelter.sqlite3',b'fake')
        with self.assertRaises(ValueError):restore_project(target,media,bad,confirmed=True)
        self.assertFalse((Path(self.temp.name)/'outside').exists())

    def test_tampered_or_missing_photo_backup_keeps_working_database(self):
        self.admin();photo=self.upload()[0]
        self.client.put('/api/admin/pets/1',json={**self.pet_body(),'image':photo['image']})
        copy=backup_project(self.app.state.database,self.app.state.media_directory)
        with zipfile.ZipFile(copy) as archive:original={name:archive.read(name) for name in archive.namelist()}
        image_path='uploads/'+photo['image'].split('/')[-1]
        for mode in ('tampered','missing'):
            data=dict(original);manifest=json.loads(data['manifest.json'])
            if mode=='tampered':data[image_path]=b'changed'
            else:
                del data[image_path];del manifest['files'][image_path]
                data['manifest.json']=json.dumps(manifest).encode()
            bad=Path(self.temp.name)/(mode+'.zip')
            with zipfile.ZipFile(bad,'w') as archive:
                for name,value in data.items():archive.writestr(name,value)
            before=file_hash(self.app.state.database.path)
            with self.assertRaises(ValueError):restore_project(self.app.state.database,self.app.state.media_directory,bad,confirmed=True)
            self.assertEqual(file_hash(self.app.state.database.path),before)
            self.assertEqual(self.client.get('/api/pets/1').json()['image'],photo['image'])

    def test_backup_with_incomplete_feature_columns_is_rejected(self):
        path=Path(self.temp.name)/'broken-schema.sqlite3'
        database=Database(path);database.initialize()
        with database.connect() as db:db.execute('ALTER TABLE pet_photos DROP COLUMN alt')
        with self.assertRaisesRegex(ValueError,'схема'):check_backup(path)


class FeatureMigrationTests(unittest.TestCase):
    def test_future_database_is_not_silently_downgraded(self):
        with TemporaryDirectory() as folder:
            database=Database(Path(folder)/'future.sqlite3');database.initialize()
            with database.connect() as db:db.execute('PRAGMA user_version=5')
            with self.assertRaisesRegex(ValueError,'новой версией'):database.initialize()
            with database.connect() as db:self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],5)

    def legacy(self,folder):
        database=Database(Path(folder)/'legacy.sqlite3')
        with database.connect() as db:
            db.executescript((ROOT/'tests/fixtures/schema-v3.sql').read_text())
            for pet in json.loads((ROOT/'backend/seed/pets.json').read_text()):db.execute(INSERT_PET,pet_values(pet))
            db.execute("INSERT INTO users(name,login,password_hash,role) VALUES ('Куратор','admin',?,'admin')",(passwords.hash('1'),))
            db.execute("INSERT INTO applications(id,user_id,pet_id,visitor_name,phone,visit_date,visit_time,status,admin_note) VALUES (42,1,1,'Посетитель','+79000000000',?,'14-16','confirmed','Старая заметка.')",(day(),))
            db.execute('PRAGMA user_version=3')
        return database

    def test_v3_migration_preserves_records_and_adds_honest_history_snapshot(self):
        with TemporaryDirectory() as folder:
            database=self.legacy(folder)
            database.initialize();database.initialize()
            with database.connect() as db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],4)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM pet_photos').fetchone()[0],15)
                event=db.execute('SELECT * FROM application_events').fetchone()
                self.assertEqual(event['kind'],'imported');self.assertEqual(event['application_id'],42)
                self.assertEqual(event['note'],'Старая заметка.');self.assertIsNone(event['actor_id'])
                self.assertEqual(db.execute('SELECT COUNT(*) FROM application_events').fetchone()[0],1)
                self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())
            copies=list((Path(folder)/'backups').glob('before-features-*.sqlite3'));self.assertEqual(len(copies),1)
            with sqlite3.connect(copies[0]) as db:self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],3)

    def test_feature_migration_is_atomic_on_failure(self):
        with TemporaryDirectory() as folder:
            database=self.legacy(folder)
            with self.assertRaises(sqlite3.DatabaseError):
                with database.connect() as db:
                    db.set_authorizer(lambda action,*args:sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_CREATE_TABLE else sqlite3.SQLITE_OK)
                    database.migrate_features(db)
            with database.connect() as db:
                self.assertNotIn('adoption_story',{row['name'] for row in db.execute('PRAGMA table_info(pets)')})
                self.assertEqual(db.execute('SELECT id FROM applications').fetchone()[0],42)
            self.assertEqual(len(list((Path(folder)/'backups').glob('before-features-*.sqlite3'))),1)


if __name__=='__main__':unittest.main()
