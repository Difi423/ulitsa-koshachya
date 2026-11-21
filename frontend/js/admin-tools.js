import { apiRequest,downloadCSV } from './api.js';
import { createElement,formatDate } from './data.js';
import { moscowToday,moscowMinutes,isISODate } from './validation.js';

const TIMES={'12-14':'12:00–14:00','14-16':'14:00–16:00','16-18':'16:00–18:00'};
const STATUSES={new:'Новая',confirmed:'Встреча согласована',completed:'Знакомство состоялось',cancelled:'Отменена'};

function addDays(day,offset) {
    const value=new Date(day+'T12:00:00Z');value.setUTCDate(value.getUTCDate()+offset);return value.toISOString().slice(0,10);
}

export function appendHistory(card,identifier) {
    const details=createElement('details','application-history');
    const summary=createElement('summary','','История заявки');
    const content=createElement('div','history-list');details.append(summary,content);card.append(details);
    let loaded=false,loading=false;
    async function load() {
        if (loaded || loading)return;
        loading=true;content.textContent='Загружаем историю…';
        try {
            const events=await apiRequest(`/api/admin/applications/${identifier}/history`);
            content.replaceChildren();summary.textContent=`История заявки (${events.length})`;
            if (!events.length)content.append(createElement('p','','Изменений пока нет.'));
            for (const event of events) {
                const item=createElement('article','history-event');
                const actor=event.actor_name || (event.kind==='created' ? 'Посетитель' : event.kind==='imported' ? 'Перенос данных' : 'Куратор');
                const when=new Intl.DateTimeFormat('ru-RU',{timeZone:'Europe/Moscow',day:'numeric',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}).format(new Date(event.created_at));
                item.append(createElement('p','small-text',`${when} (МСК) · ${actor}`));
                if (event.kind==='created')item.append(createElement('p','','Заявка получена.'));
                else if (event.kind==='imported')item.append(createElement('p','','Состояние на момент обновления сайта. Более ранние изменения не записывались.'));
                if (event.old_status!==event.new_status) {
                    item.append(createElement('p','',event.old_status
                        ? `${STATUSES[event.old_status]} → ${STATUSES[event.new_status]}` : `Статус: ${STATUSES[event.new_status]}`));
                }
                if (event.old_visit_date && (event.old_visit_date!==event.new_visit_date || event.old_visit_time!==event.new_visit_time)) {
                    item.append(createElement('p','',`Встреча перенесена: ${formatDate(event.old_visit_date)}, ${TIMES[event.old_visit_time]} → ${formatDate(event.new_visit_date)}, ${TIMES[event.new_visit_time]}`));
                }
                if (event.old_note && event.old_note!==event.note)item.append(createElement('p','user-text',`Прежняя заметка: ${event.old_note}`));
                if (event.note)item.append(createElement('p','user-text',`Заметка: ${event.note}`));
                content.append(item);
            }
            loaded=true;
        } catch(error) {
            content.textContent=error.message;
            const retry=createElement('button','text-button','Повторить загрузку истории');retry.type='button';retry.addEventListener('click',load);content.append(retry);
        } finally {loading=false;}
    }
    details.addEventListener('toggle',() => {if (details.open)load();});
}

export function initCalendar(openApplication) {
    const field=document.querySelector('#calendar-day');field.value=moscowToday();
    const status=document.querySelector('#calendar-status');const grid=document.querySelector('#calendar-grid');
    let sequence=0;
    async function load() {
        if (!isISODate(field.value)) {status.textContent='Выберите корректную дату.';return;}
        const ticket=++sequence;
        const day=new Date(field.value+'T12:00:00Z');
        const first=addDays(field.value,-((day.getUTCDay()+6)%7)),last=addDays(first,6);
        status.textContent='Загружаем расписание…';
        try {
            const data=await apiRequest(`/api/admin/calendar?${new URLSearchParams({from:first,to:last})}`);
            if (ticket!==sequence)return;
            document.querySelector('#calendar-range').textContent=`${formatDate(first)} — ${formatDate(last)}`;
            grid.replaceChildren();
            for (let index=0;index<7;index++) {
                const value=addDays(first,index),monday=new Date(value+'T12:00:00Z').getUTCDay()===1;
                const column=createElement('section',`calendar-day${value===moscowToday() ? ' is-today' : ''}`);
                column.append(createElement('h4','',formatDate(value,{weekday:'short',day:'numeric',month:'short',year:undefined})));
                if (monday)column.append(createElement('p','small-text','Выходной'));
                for (const [time,label] of Object.entries(TIMES)) {
                    const items=data.items.filter(item => item.visit_date===value && item.visit_time===time);
                    const confirmed=items.filter(item => item.status==='confirmed').length;
                    const past=value<moscowToday() || (value===moscowToday() && Number(time.slice(0,2))*60<=moscowMinutes());
                    const slot=createElement('div',`calendar-slot${confirmed>=data.capacity ? ' is-occupied' : ''}`);
                    slot.append(createElement('p','slot-time',label),createElement('p','small-text',
                        confirmed ? `Подтверждено: ${confirmed}/${data.capacity}` : monday || past ? 'Запись закрыта' : 'Свободно для согласования'));
                    for (const item of items) {
                        const control=createElement('button',`calendar-appointment status-${item.status}`,
                            `№${item.id} · ${item.pet_name}\n${item.visitor_name}\n${STATUSES[item.status]}`);
                        control.type='button';control.addEventListener('click',() => openApplication(item.id));slot.append(control);
                    }
                    if (confirmed>data.capacity)slot.append(createElement('p','calendar-conflict','Есть пересечение встреч. Перенесите одну из них.'));
                    column.append(slot);
                }
                grid.append(column);
            }
            status.textContent=`Встреч в одном интервале: до ${data.capacity}. Нажмите заявку, чтобы открыть её.`;
        } catch(error) {if (ticket===sequence)status.textContent=error.message;}
    }
    document.querySelector('#calendar-prev').addEventListener('click',() => {field.value=addDays(field.value || moscowToday(),-7);load();});
    document.querySelector('#calendar-next').addEventListener('click',() => {field.value=addDays(field.value || moscowToday(),7);load();});
    document.querySelector('#calendar-today').addEventListener('click',() => {field.value=moscowToday();load();});
    document.querySelector('#calendar-refresh').addEventListener('click',load);field.addEventListener('change',load);
    return {load};
}

function chart(series) {
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    svg.setAttribute('viewBox','0 0 720 220');svg.setAttribute('role','img');svg.setAttribute('aria-label','Количество поступивших заявок по дням выбранного периода');
    const node=(tag,attributes,text='') => {
        const element=document.createElementNS('http://www.w3.org/2000/svg',tag);
        for (const [key,value] of Object.entries(attributes))element.setAttribute(key,String(value));
        if (text)element.textContent=text;svg.append(element);return element;
    };
    const maximum=Math.max(1,...series.map(item => item.count));
    for (const value of [0,maximum]) {
        const y=176-value/maximum*146;
        node('line',{x1:40,x2:700,y1:y,y2:y,class:'chart-gridline'});
        node('text',{x:28,y:y+5,'text-anchor':'end',class:'chart-label'},String(value));
    }
    const point=(item,index) => ({x:series.length===1 ? 370 : 40+index/(series.length-1)*660,y:176-item.count/maximum*146});
    node('polyline',{points:series.map((item,index) => {const p=point(item,index);return `${p.x},${p.y}`;}).join(' '),class:'chart-line'});
    const tick=Math.max(1,Math.ceil(series.length/5));
    series.forEach((item,index) => {
        const p=point(item,index);
        const dot=node('circle',{cx:p.x,cy:p.y,r:series.length>40 ? 2 : 4,class:'chart-dot'});
        const title=document.createElementNS('http://www.w3.org/2000/svg','title');title.textContent=`${formatDate(item.date)}: ${item.count}`;dot.append(title);
        if (index%tick===0 || index===series.length-1)node('text',{x:p.x,y:205,'text-anchor':index===0 ? 'start' : index===series.length-1 ? 'end' : 'middle',class:'chart-label'},item.date.slice(8)+'.'+item.date.slice(5,7));
    });
    return svg;
}

export function initStatistics() {
    const form=document.querySelector('#statistics-form');
    const first=document.querySelector('#statistics-from'),last=document.querySelector('#statistics-to');
    last.value=moscowToday();first.value=last.value.slice(0,8)+'01';
    const status=document.querySelector('#statistics-status'),content=document.querySelector('#statistics-content');
    const download=document.querySelector('#statistics-csv');let loaded=null,sequence=0;
    async function load() {
        if (!first.value || !last.value)return;
        const ticket=++sequence;status.textContent='Считаем статистику…';download.disabled=true;
        try {
            const data=await apiRequest(`/api/admin/statistics?${new URLSearchParams({from:first.value,to:last.value})}`);
            if (ticket!==sequence)return;
            loaded={from:data.from,to:data.to};
            const totals=document.querySelector('#statistics-totals');totals.replaceChildren();
            for (const [key,label] of Object.entries({all:'Всего заявок',new:'Новые',confirmed:'Согласованы',completed:'Состоялись',cancelled:'Отменены'})) {
                const tile=createElement('div');tile.append(createElement('strong','',String(data.totals[key])),createElement('span','',label));totals.append(tile);
            }
            document.querySelector('#statistics-chart').replaceChildren(chart(data.daily));
            const table=createElement('table','report-table');
            const head=createElement('thead'),headRow=createElement('tr');headRow.append(createElement('th','','Дата'),createElement('th','','Заявки'));head.append(headRow);
            const body=createElement('tbody');
            data.daily.forEach(item => {const row=createElement('tr');row.append(createElement('td','',formatDate(item.date)),createElement('td','',String(item.count)));body.append(row);});
            table.append(head,body);document.querySelector('#statistics-table').replaceChildren(table);
            const popular=document.querySelector('#statistics-popular');popular.replaceChildren();
            const max=Math.max(1,...data.popular.map(pet => pet.count));
            if (!data.popular.length)popular.append(createElement('p','small-text','В этом периоде заявок ещё не было.'));
            data.popular.forEach(pet => {
                const row=createElement('div','popular-row'),label=createElement('p','',`${pet.name} — ${pet.count}`);
                const bar=createElement('progress');bar.value=pet.count;bar.max=max;bar.setAttribute('aria-label',`Заявок на знакомство с ${pet.name}`);row.append(label,bar);popular.append(row);
            });
            const pets=document.querySelector('#statistics-pets'),list=createElement('dl','report-list');
            for (const [key,label] of Object.entries({available:'Ищут дом',reserved:'Знакомятся с семьёй',adopted:'Уже дома',archived:'В архиве'})) {
                const row=createElement('div');row.append(createElement('dt','',label),createElement('dd','',String(data.pets[key])));list.append(row);
            }
            pets.replaceChildren(list);document.querySelector('#statistics-adopted').textContent=`Нашли дом за выбранный период: ${data.adoptedInPeriod}`;
            content.hidden=false;download.disabled=false;
            status.textContent=`Период: ${formatDate(data.from)} — ${formatDate(data.to)} CSV содержит заявки за этот период.`;
        } catch(error) {if (ticket===sequence)status.textContent=error.message;}
    }
    form.addEventListener('submit',event => {event.preventDefault();load();});
    download.addEventListener('click',async () => {
        if (!loaded)return;
        download.disabled=true;
        try {await downloadCSV(`/api/admin/applications.csv?${new URLSearchParams(loaded)}`);status.textContent='CSV выгружен. Его можно открыть в Excel.';}
        catch(error) {status.textContent=error.message;}
        finally {download.disabled=false;}
    });
    return {load};
}
