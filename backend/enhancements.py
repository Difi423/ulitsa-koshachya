"""Расписание, журнал заявок и отчёты. Все персональные сведения — только куратору."""
import csv
from datetime import date, datetime, timedelta
from io import StringIO

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from .database import APPLICATION_STATUS
from .media import upload_images
from .models import MOSCOW
from .security import require_admin

SLOTS = {'12-14':'12:00–14:00', '14-16':'14:00–16:00', '16-18':'16:00–18:00'}
APPLICATION_ROWS = '''SELECT applications.*,pets.name AS pet_name,pets.slug AS pet_slug
    FROM applications JOIN pets ON pets.id=applications.pet_id'''


def iso_day(value):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError()
        return parsed
    except (ValueError, TypeError):
        raise HTTPException(422, 'Укажите дату в формате ГГГГ-ММ-ДД.') from None


def date_period(start, end, maximum=366, calendar=False):
    today = datetime.now(MOSCOW).date()
    first = iso_day(start) if start else (today-timedelta(days=today.weekday()) if calendar else today.replace(day=1))
    last = iso_day(end) if end else (first+timedelta(days=6) if calendar else today)
    if first > last or (last-first).days >= maximum:
        raise HTTPException(422, f'Выберите период от 1 до {maximum} дней.')
    return first.isoformat(), last.isoformat()


def slot_closed(day, slot, now=None):
    now = now or datetime.now(MOSCOW)
    parsed = iso_day(day)
    if parsed < now.date():
        return 'Дата визита уже прошла.'
    if parsed.weekday() == 0:
        return 'По понедельникам приют закрыт.'
    if parsed == now.date() and int(slot[:2])*60 <= now.hour*60+now.minute:
        return 'Этот интервал уже начался. Выберите более позднее время.'
    return ''


def slot_full(db, day, slot, capacity, excluding=0):
    count = db.execute("""SELECT COUNT(*) FROM applications
        WHERE visit_date=? AND visit_time=? AND status='confirmed' AND id!=?""", (day,slot,excluding)).fetchone()[0]
    return count >= capacity


def record_event(db, application_id, kind, actor=None, previous=None):
    current = db.execute('SELECT * FROM applications WHERE id=?', (application_id,)).fetchone()
    db.execute('''INSERT INTO application_events
        (application_id,actor_id,kind,old_status,new_status,old_visit_date,new_visit_date,
         old_visit_time,new_visit_time,old_note,note) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
        (application_id,actor,kind,previous['status'] if previous else None,current['status'],
         previous['visit_date'] if previous else '',current['visit_date'],
         previous['visit_time'] if previous else '',current['visit_time'],
         previous['admin_note'] if previous else '',current['admin_note']))


def csv_cell(value):
    value = str(value if value is not None else '')
    if value[:1] in ('\t','\r','\n') or value.lstrip(' \t\r\n').startswith(('=','+','-','@')):
        return "'" + value
    return value


def feature_routes(database, settings, media_directory):
    router = APIRouter()

    @router.post('/api/admin/uploads', status_code=201, tags=['Админка'])
    async def upload(files: list[UploadFile] = File(...), user=Depends(require_admin)):
        return await upload_images(files, media_directory)

    @router.get('/api/availability', tags=['Заявки'])
    def availability(day: str = Query(alias='date'), pet_id: int = Query(gt=0)):
        iso_day(day)
        with database.connect() as db:
            pet = db.execute('SELECT status FROM pets WHERE id=?', (pet_id,)).fetchone()
            if pet is None or pet['status'] != 'available':
                raise HTTPException(409, 'Этот питомец сейчас недоступен для знакомства.')
            slots = []
            for value,label in SLOTS.items():
                reason = slot_closed(day,value)
                full = slot_full(db,day,value,settings.slot_capacity)
                slots.append({'value':value,'label':label,'available':not reason and not full,
                              'reason':reason or ('Время уже занято подтверждёнными встречами.' if full else '')})
        return {'date':day,'slots':slots}

    @router.get('/api/admin/calendar', tags=['Админка'])
    def calendar(start: str | None = Query(default=None, alias='from'),
                 end: str | None = Query(default=None, alias='to'), user=Depends(require_admin)):
        first,last = date_period(start,end,93,calendar=True)
        with database.connect() as db:
            rows = db.execute(APPLICATION_ROWS+" WHERE visit_date BETWEEN ? AND ? AND applications.status!='cancelled' ORDER BY visit_date,visit_time,applications.id", (first,last)).fetchall()
        return {'from':first,'to':last,'capacity':settings.slot_capacity,'items':[dict(row) for row in rows]}

    @router.get('/api/admin/applications/{application_id}/history', tags=['Админка'])
    def history(application_id: int, user=Depends(require_admin)):
        with database.connect() as db:
            if db.execute('SELECT id FROM applications WHERE id=?', (application_id,)).fetchone() is None:
                raise HTTPException(404, 'Заявка не найдена.')
            rows = db.execute('''SELECT application_events.*,users.name AS actor_name
                FROM application_events LEFT JOIN users ON users.id=application_events.actor_id
                WHERE application_id=? ORDER BY application_events.id''', (application_id,)).fetchall()
        return [dict(row) for row in rows]

    @router.get('/api/admin/statistics', tags=['Админка'])
    def statistics(start: str | None = Query(default=None, alias='from'),
                   end: str | None = Query(default=None, alias='to'), user=Depends(require_admin)):
        first,last = date_period(start,end)
        where = "date(applications.created_at,'+3 hours') BETWEEN ? AND ?"
        with database.connect() as db:
            statuses = {row['status']:row['count'] for row in db.execute(
                'SELECT status,COUNT(*) AS count FROM applications WHERE '+where+' GROUP BY status', (first,last))}
            daily = {row['day']:row['count'] for row in db.execute(
                "SELECT date(created_at,'+3 hours') AS day,COUNT(*) AS count FROM applications WHERE "+where+" GROUP BY day", (first,last))}
            popular = [dict(row) for row in db.execute('''SELECT pets.id,pets.name,COUNT(*) AS count
                FROM applications JOIN pets ON pets.id=applications.pet_id WHERE '''+where+
                ' GROUP BY pets.id,pets.name ORDER BY count DESC,pets.name LIMIT 5', (first,last))]
            pets = {row['status']:row['count'] for row in db.execute('SELECT status,COUNT(*) AS count FROM pets GROUP BY status')}
            adopted = db.execute("SELECT COUNT(*) FROM pets WHERE status='adopted' AND adopted_at BETWEEN ? AND ?", (first,last)).fetchone()[0]
        first_day,last_day = iso_day(first),iso_day(last)
        series = [{'date':(first_day+timedelta(days=offset)).isoformat(),
                   'count':daily.get((first_day+timedelta(days=offset)).isoformat(),0)}
                  for offset in range((last_day-first_day).days+1)]
        return {'from':first,'to':last,'totals':{'all':sum(statuses.values()),
                **{key:statuses.get(key,0) for key in APPLICATION_STATUS}},
                'pets':{key:pets.get(key,0) for key in ('available','reserved','adopted','archived')},
                'adoptedInPeriod':adopted,'daily':series,'popular':popular}

    @router.get('/api/admin/applications.csv', tags=['Админка'])
    def export(start: str | None = Query(default=None, alias='from'),
               end: str | None = Query(default=None, alias='to'), user=Depends(require_admin)):
        first,last = date_period(start,end)
        with database.connect() as db:
            rows = db.execute(APPLICATION_ROWS+" WHERE date(applications.created_at,'+3 hours') BETWEEN ? AND ? ORDER BY applications.id", (first,last)).fetchall()
        output = StringIO(newline='')
        writer = csv.writer(output, delimiter=';')
        writer.writerow(['Номер','Питомец','Посетитель','Телефон','Дата визита','Время','Статус','Комментарий','Заметка куратора','Получена (МСК)'])
        for row in rows:
            received = datetime.fromisoformat(row['created_at'].replace('Z','+00:00')).astimezone(MOSCOW).strftime('%Y-%m-%d %H:%M')
            writer.writerow([csv_cell(value) for value in (row['id'],row['pet_name'],row['visitor_name'],row['phone'],
                row['visit_date'],SLOTS[row['visit_time']],APPLICATION_STATUS[row['status']],row['comment'],row['admin_note'],received)])
        return Response(content=('\ufeff'+output.getvalue()).encode('utf-8'), media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition':f'attachment; filename="applications-{first}-{last}.csv"'})

    return router
