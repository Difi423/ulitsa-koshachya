import { apiRequest, getSession, adminLoginLink } from './api.js';
import { createElement } from './data.js';
import { bindValidation,moscowToday,isISODate } from './validation.js';
import { applicationCard } from './records.js';
import { initPhotoEditor } from './photo-editor.js';
import { initCalendar,initStatistics,appendHistory } from './admin-tools.js';

const PET_KEYS = ['slug', 'name', 'ageMonths', 'sex', 'temperament', 'trait', 'color',
    'short', 'story', 'home', 'care', 'image', 'alt', 'featured', 'status','adoptionStory','adoptedAt'];
const APPLICATION_STATUS = { new: 'Новая', confirmed: 'Встреча согласована', completed: 'Знакомство состоялось', cancelled: 'Отменена' };
const MESSAGE_STATUS = { new: 'Новое', read: 'Прочитано', closed: 'Закрыто' };

export async function initAdmin() {
    const area = document.querySelector('#admin-area');
    if (!area) return;
    const status = document.querySelector('#admin-status');
    const form = document.querySelector('#pet-form');
    let pets = [];
    let applications = [];
    let editingId = null;
    let photoEditor,calendar,statistics;

    function say(text) { status.textContent = text; }
    function button(text, action, secondary = true) {
        const control = createElement('button', `button button-small${secondary ? ' button-secondary' : ''}`, text);
        control.type = 'button';
        control.addEventListener('click', async () => {
            control.disabled = true;
            try { await action(); }
            catch (error) { say(error.message); }
            finally { control.disabled = false; }
        });
        return control;
    }
    function options(values, selected) {
        const select = createElement('select');
        for (const [value, label] of Object.entries(values)) select.append(new Option(label, value, false, value === selected));
        return select;
    }
    function petPayload(pet) { return {...Object.fromEntries(PET_KEYS.map(key => [key, pet[key]])),photos:pet.photos.map(photo => ({image:photo.image,alt:photo.alt}))}; }

    function openEditor(pet = null) {
        form.reset();
        editingId = pet?.id || null;
        document.querySelector('#pet-editor-title').textContent = pet ? `Карточка: ${pet.name}` : 'Новый питомец';
        for (const key of PET_KEYS) {
            const field = form.elements.namedItem(key);
            if (key === 'featured') field.checked = pet?.featured || false;
            else if (key === 'temperament') {
                for (const option of field.options) option.selected = (pet?.temperament || ['calm']).includes(option.value);
            } else field.value = pet ? pet[key] : ({ ageMonths: 12, sex: 'female', status: 'available' }[key] ?? '');
        }
        form.hidden = false;
        document.querySelector('#pet-form-result').hidden = true;
        form.querySelector('#pet-name').focus();
        photoEditor.open(pet);
        form.elements.adoptedAt.max=moscowToday();
        updatePhoto();
    }

    function updatePhoto() {
        const photo = document.querySelector('#pet-editor-photo');
        const value = form.elements.image.value;
        photo.hidden = !value;
        if (value) photo.src = value;
    }

    function renderPets() {
        const container = document.querySelector('#admin-pets');
        const filter = document.querySelector('#admin-pet-filter').value;
        const shown = pets.filter(pet => filter === 'all' || (filter === 'archived' ? pet.status === 'archived' : pet.status !== 'archived'));
        container.replaceChildren();
        document.querySelector('#admin-pet-count').textContent = `Показано: ${shown.length} из ${pets.length}`;
        if (!shown.length) container.append(createElement('p', 'empty-state', 'Питомцев в этом разделе пока нет.'));
        for (const pet of shown) {
            const row = createElement('article', 'admin-pet-row');
            const image = createElement('img');
            image.src = pet.image; image.alt = pet.alt; image.width = 88; image.height = 88; image.loading = 'lazy';
            const content = createElement('div', 'admin-pet-info');
            const title = createElement('a', '', pet.name);
            title.href = `pet.html?id=${pet.id}`;
            content.append(title, createElement('p', 'small-text', `${pet.sexLabel} · ${pet.age}`),
                createElement('span', 'status-badge', pet.statusLabel));
            const actions = createElement('div', 'row-actions');
            actions.append(button('Изменить', () => openEditor(pet)));
            if (pet.status === 'archived') {
                actions.append(button('Восстановить', async () => {
                    await apiRequest(`/api/admin/pets/${pet.id}`, { method: 'PUT', body: { ...petPayload(pet), status: 'available' } });
                    await loadPets(); say(`${pet.name}: карточка восстановлена.`);
                }));
            } else {
                actions.append(button('В архив', async () => {
                    await apiRequest(`/api/admin/pets/${pet.id}`, { method: 'DELETE' });
                    await loadPets(); say(`${pet.name}: карточка в архиве. Её можно восстановить.`);
                }));
            }
            row.append(image, content, actions);
            container.append(row);
        }
    }

    async function loadPets() {
        pets = await apiRequest('/api/admin/pets');
        document.querySelector('#stat-pets').textContent = pets.filter(pet => pet.status !== 'archived').length;
        renderPets();
    }

    async function loadApplications() {
        applications = await apiRequest('/api/admin/applications');
        document.querySelector('#stat-applications').textContent = applications.filter(item => item.status === 'new').length;
        renderApplications();
    }

    function renderApplications() {
        const filter = document.querySelector('#application-status-filter').value;
        const query = document.querySelector('#application-search').value.trim().toLocaleLowerCase('ru-RU');
        const phoneQuery = query.replace(/\D/g, '');
        const items = applications.filter(item => {
            const text = `${item.id} ${item.visitor_name} ${item.pet_name} ${item.phone}`.toLocaleLowerCase('ru-RU');
            const matches = !query || text.includes(query) ||
                (/^[+\d\s()-]+$/.test(query) && phoneQuery && item.phone.replace(/\D/g, '').includes(phoneQuery));
            return (filter === 'all' || item.status === filter) && matches;
        });
        document.querySelector('#application-count').textContent = `Показано: ${items.length} из ${applications.length}`;
        const container = document.querySelector('#admin-applications');
        container.replaceChildren();
        if (!items.length) container.append(createElement('p', 'empty-state', applications.length
            ? 'По выбранным условиям заявок нет.' : 'Заявок на знакомство пока нет.'));
        for (const item of items) {
            const card = applicationCard(item);
            const phone = createElement('a', '', item.phone);
            phone.href = `tel:${item.phone}`;
            const contact = createElement('p', 'user-text', `${item.visitor_name} · `);
            contact.append(phone);
            card.append(contact);
            const changes = { new: ['new', 'confirmed', 'cancelled'], confirmed: ['confirmed', 'completed', 'cancelled'],
                completed: ['completed'], cancelled: ['cancelled'] }[item.status];
            const select = options(Object.fromEntries(changes.map(key => [key, APPLICATION_STATUS[key]])), item.status);
            select.id = `application-status-${item.id}`;
            const label = createElement('label', '', 'Статус заявки'); label.htmlFor = select.id;
            const note = createElement('textarea');
            note.id = `application-note-${item.id}`; note.maxLength = 1500; note.rows = 2; note.value = item.admin_note;
            const noteLabel = createElement('label', '', 'Заметка куратора'); noteLabel.htmlFor = note.id;
            const actions = createElement('div', 'record-controls');
            actions.append(label, select);
            let day,interval;
            if (['new','confirmed'].includes(item.status)) {
                const visit=createElement('div','form-grid');
                day=createElement('input');day.type='date';day.id=`application-day-${item.id}`;day.value=item.visit_date;
                const dayLabel=createElement('label','','Дата встречи');dayLabel.htmlFor=day.id;
                interval=options({'12-14':'12:00–14:00','14-16':'14:00–16:00','16-18':'16:00–18:00'},item.visit_time);interval.id=`application-time-${item.id}`;
                const timeLabel=createElement('label','','Время встречи');timeLabel.htmlFor=interval.id;
                const dateField=createElement('div','field');dateField.append(dayLabel,day);
                const timeField=createElement('div','field');timeField.append(timeLabel,interval);visit.append(dateField,timeField);actions.append(visit);
            }
            const feedback=createElement('p','small-text');feedback.setAttribute('role','alert');
            actions.append(noteLabel,note,button('Сохранить заявку',async () => {
                const body={status:select.value,admin_note:note.value};
                if (day && day.value!==item.visit_date)body.visit_date=day.value;
                if (interval && interval.value!==item.visit_time)body.visit_time=interval.value;
                try {
                    await apiRequest(`/api/admin/applications/${item.id}`,{method:'PATCH',body});
                    await loadApplications();say(`Заявка №${item.id} обновлена.`);
                } catch(error) {feedback.textContent=error.message;say(error.message);}
            },false),feedback);
            card.append(actions); container.append(card);
            appendHistory(card,item.id);
        }
    }

    async function loadMessages() {
        const items = await apiRequest('/api/admin/messages');
        document.querySelector('#stat-messages').textContent = items.filter(item => item.status === 'new').length;
        const container = document.querySelector('#admin-messages'); container.replaceChildren();
        if (!items.length) container.append(createElement('p', 'empty-state', 'Сообщений пока нет.'));
        const topics = { adoption: 'Знакомство с питомцем', volunteer: 'Волонтёрство', help: 'Помощь приюту', question: 'Другой вопрос' };
        for (const item of items) {
            const card = createElement('article', 'record-card');
            card.append(createElement('h3', '', `№${item.id} · ${topics[item.topic]}`),
                createElement('p', '', item.name),
                createElement('p', 'user-text', item.message));
            const select = options(MESSAGE_STATUS, item.status); select.id = `message-status-${item.id}`;
            const label = createElement('label', '', 'Статус сообщения'); label.htmlFor = select.id;
            const controls = createElement('div', 'record-controls');
            controls.append(label, select, button('Сохранить статус', async () => {
                await apiRequest(`/api/admin/messages/${item.id}`, { method: 'PATCH', body: { status: select.value } });
                await loadMessages(); say(`Сообщение №${item.id} обновлено.`);
            }, false));
            card.append(controls); container.append(card);
        }
    }

    try {
        const { user } = await getSession();
        if (user?.role !== 'admin') {
            location.replace(adminLoginLink());
            return;
        }
        const photos = await apiRequest('/api/admin/photos');
        form.elements.image.replaceChildren(new Option('Выберите фотографию', ''),
            ...photos.map(path => new Option(path.split('/').pop(), path)));
        photoEditor=initPhotoEditor(form);
        calendar=initCalendar(async identifier => {
            try { await loadApplications(); } catch(error) {say(error.message);return;}
            document.querySelector('[data-admin-tab="applications"]').click();
            document.querySelector('#application-search').value=String(identifier);
            document.querySelector('#application-status-filter').value='all';renderApplications();
            document.querySelector(`#application-status-${identifier}`)?.focus();
        });
        statistics=initStatistics();
        const rules = {};
        for (const field of form.querySelectorAll('[required]')) {
            rules[field.id] = value => value.trim() ? '' : 'Заполните это поле.';
        }
        rules['pet-age'] = value => /^\d+$/.test(value) && Number(value) <= 360 ? '' : 'Введите возраст в месяцах от 0 до 360.';
        rules['pet-slug'] = value => /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value) ? '' : 'Используйте латинские буквы, цифры и дефис.';
        rules['pet-adopted-date']=value => !value || (isISODate(value) && value<=moscowToday()) ? '' : 'Укажите дату пристройства, не в будущем.';
        bindValidation(form, rules, async (values, result) => {
            const body = { ...values, ageMonths: Number(values.ageMonths), featured: values.featured === 'on',
                temperament: [...form.elements.temperament.selectedOptions].map(option => option.value),photos:photoEditor.values() };
            const pet = await apiRequest(editingId ? `/api/admin/pets/${editingId}` : '/api/admin/pets', {
                method: editingId ? 'PUT' : 'POST', body,
            });
            result.textContent = 'Карточка сохранена.';
            form.hidden = true;
            await loadPets(); say(`${pet.name}: карточка сохранена.`);
        });
        document.querySelector('#add-pet').addEventListener('click', () => openEditor());
        document.querySelector('#close-pet-editor').addEventListener('click', () => { form.hidden = true; });
        form.elements.image.addEventListener('change', updatePhoto);
        document.querySelector('#admin-pet-filter').addEventListener('change', renderPets);
        document.querySelector('#application-status-filter').addEventListener('change', renderApplications);
        document.querySelector('#application-search').addEventListener('input', renderApplications);
        document.querySelector('#refresh-applications').addEventListener('click', async event => {
            const control = event.currentTarget;
            control.disabled = true;
            try { await loadApplications(); say('Список заявок обновлён.'); }
            catch (error) { say(error.message); }
            finally { control.disabled = false; }
        });
        for (const tab of document.querySelectorAll('[data-admin-tab]')) {
            tab.addEventListener('click', () => {
                for (const other of document.querySelectorAll('[data-admin-tab]')) {
                    other.setAttribute('aria-pressed', String(other === tab));
                    document.querySelector(`#admin-section-${other.dataset.adminTab}`).hidden = other !== tab;
                }
                say('');
                if (tab.dataset.adminTab==='calendar')calendar.load();
                if (tab.dataset.adminTab==='statistics')statistics.load();
            });
        }
        area.hidden = false;
        say('Загружаем данные…');
        await Promise.all([loadPets(), loadApplications(), loadMessages()]);
        say('');
    } catch (error) {
        say(error.message);
        const retry = button('Повторить загрузку', () => location.reload());
        status.append(document.createTextNode(' '), retry);
    }
}
