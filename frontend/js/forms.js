import { createElement } from './data.js';
import { apiRequest } from './api.js';
import {
    bindValidation, addResultLine, moscowToday, validateName,
    validatePhone, normalizePhone, validateMessage, validateVisitDate, validateVisitTime,
} from './validation.js';

function resultHeading(result, title, message) {
    result.replaceChildren();
    result.append(createElement('h3', '', title), createElement('p', '', message));
    const list = createElement('dl', 'result-list');
    result.append(list);
    return list;
}

export function initFeedback() {
    const form = document.querySelector('#feedback-form');
    if (!form) return;
    bindValidation(form, {
        'feedback-name': validateName,
        'feedback-topic': value => ['adoption', 'volunteer', 'help', 'question'].includes(value)
            ? '' : 'Выберите тему сообщения.',
        'feedback-message': validateMessage,
    }, async (values, result) => {
        const response = await apiRequest('/api/messages', { method: 'POST', anonymous: true, body: {
            name: values.name, topic: values.topic, message: values.message,
        } });
        const list = resultHeading(result, `Сообщение №${response.id} отправлено`,
            'Спасибо! Куратор увидит ваше сообщение.');
        addResultLine(list, 'Имя', values.name.trim());
        const topic = form.querySelector('#feedback-topic').selectedOptions[0].textContent;
        addResultLine(list, 'Тема', topic);
        addResultLine(list, 'Сообщение', values.message.trim());
    });
}

export async function initApplication(allPets) {
    const pets = allPets.filter(pet => pet.status === 'available');
    const form = document.querySelector('#application-form');
    const select = document.querySelector('#chosen-pet');
    const date = document.querySelector('#visit-date');
    const timeSelect = document.querySelector('#visit-time');
    const availability = document.querySelector('#availability-status');
    const availabilityRetry = document.querySelector('#availability-retry');
    const submitButton = form.querySelector('[type="submit"]');
    let availabilitySequence = 0;
    const photo = document.querySelector('#chosen-pet-photo');
    const info = document.querySelector('#chosen-pet-info');
    const requestedSlug = new URLSearchParams(location.search).get('pet');
    const requestedPet = pets.find(pet => pet.slug === requestedSlug);
    const initialSlug = requestedSlug === null ? (pets[0]?.slug || '') : (requestedPet?.slug || '');

    const placeholder = new Option('Выберите питомца', '', initialSlug === '', initialSlug === '');
    select.replaceChildren(placeholder, ...pets.map(pet => new Option(
        `${pet.name} — ${pet.age}`, pet.slug, pet.slug === initialSlug, pet.slug === initialSlug,
    )));

    function updateSelectedPet() {
        const pet = pets.find(item => item.slug === select.value);
        photo.hidden = !pet;
        info.replaceChildren();
        if (!pet) {
            info.textContent = 'Выберите питомца из списка.';
            return;
        }
        photo.src = pet.image;
        photo.alt = pet.alt;
        const link = createElement('a', '', `${pet.name}, ${pet.age}`);
        link.href = `pet.html?id=${pet.id}`;
        info.append(link, document.createTextNode(` — ${pet.short}`));
    }

    date.min = moscowToday();
    date.addEventListener('focus', () => { date.min = moscowToday(); });
    async function refreshAvailability() {
        const ticket=++availabilitySequence;
        availabilityRetry.hidden=true;
        const pet=pets.find(item => item.slug===select.value);
        if (!pet || !date.value || validateVisitDate(date.value)) {
            for (const option of timeSelect.options)option.disabled=false;
            availability.textContent='Выберите питомца и подходящую дату, чтобы проверить свободное время.';
            submitButton.disabled=pets.length===0;
            return;
        }
        availability.textContent='Проверяем свободное время…';submitButton.disabled=true;
        try {
            const data=await apiRequest(`/api/availability?${new URLSearchParams({date:date.value,pet_id:pet.id})}`,{anonymous:true});
            if (ticket!==availabilitySequence)return;
            const selected=timeSelect.value;
            timeSelect.replaceChildren(new Option('Выберите время',''),...data.slots.map(slot => {
                const option=new Option(slot.label+(slot.available ? '' : ' — недоступно'),slot.value);
                option.disabled=!slot.available;return option;
            }));
            if (data.slots.some(slot => slot.value===selected && slot.available))timeSelect.value=selected;
            availability.textContent=data.slots.some(slot => slot.available)
                ? 'Свободные интервалы доступны для согласования. Встречу подтвердит куратор.'
                : 'Свободных интервалов на этот день нет. Выберите другую дату.';
            timeSelect.dispatchEvent(new Event('change'));
        } catch(error) {
            if (ticket!==availabilitySequence)return;
            for (const option of timeSelect.options)option.disabled=false;
            availability.textContent='Не удалось проверить расписание. Время будет проверено при отправке заявки.';
            availabilityRetry.hidden=false;
        } finally {
            if (ticket===availabilitySequence && form.getAttribute('aria-busy')!=='true')submitButton.disabled=pets.length===0;
        }
    }
    select.addEventListener('change',() => {updateSelectedPet();refreshAvailability();});
    date.addEventListener('change',refreshAvailability);
    availabilityRetry.addEventListener('click',refreshAvailability);
    form.addEventListener('reset', () => setTimeout(() => {updateSelectedPet();refreshAvailability();}, 0));
    bindValidation(form, {
        'chosen-pet': value => pets.some(pet => pet.slug === value)
            ? '' : 'Выберите питомца, с которым хотите познакомиться.',
        'visitor-name': validateName,
        'visitor-phone': validatePhone,
        'visit-date': validateVisitDate,
        'visit-time': value => validateVisitTime(value, date.value),
        'visitor-comment': value => value.trim().length <= 1500
            ? '' : 'Комментарий должен быть не длиннее 1500 символов.',
        'visit-confirm': checked => checked
            ? '' : 'Подтвердите, что время встречи нужно согласовать с куратором.',
    }, async (values, result) => {
        const pet = pets.find(item => item.slug === values.pet);
        const response = await apiRequest('/api/applications', { method: 'POST', anonymous: true, body: {
            pet_id: pet.id, visitor_name: values.visitor_name, phone: values.phone,
            visit_date: values.visit_date, visit_time: values.visit_time,
            comment: values.comment, confirmed: values.visit_confirm === 'on',
        } });
        const list = resultHeading(result, `Заявка №${response.id} отправлена`,
            'Куратор позвонит по указанному телефону и согласует время встречи. Дождитесь звонка перед визитом.');
        addResultLine(list, 'Питомец', pet.name);
        addResultLine(list, 'Имя', values.visitor_name.trim());
        addResultLine(list, 'Телефон', normalizePhone(values.phone));
        const day = new Intl.DateTimeFormat('ru-RU', {
            timeZone: 'Europe/Moscow', day: 'numeric', month: 'long', year: 'numeric',
        }).format(new Date(`${values.visit_date}T12:00:00+03:00`));
        const time = form.querySelector('#visit-time').selectedOptions[0].textContent;
        addResultLine(list, 'Визит', `${day}, ${time} (московское время)`);
        if (values.comment.trim()) addResultLine(list, 'Комментарий', values.comment.trim());
    });

    // Если дата изменилась, ранее выбранный интервал проверяем ещё раз.
    date.addEventListener('change', () => {
        form.querySelector('#visit-time').dispatchEvent(new Event('change'));
    });
    updateSelectedPet();
    refreshAvailability();
    const submit = form.querySelector('[type="submit"]');
    submit.disabled = pets.length === 0;
    if (requestedSlug !== null && !requestedPet) {
        select.setAttribute('aria-invalid', 'true');
        const error = document.querySelector('#chosen-pet-error');
        error.textContent = 'Питомец по этой ссылке не найден. Выберите его из списка.';
        error.hidden = false;
    }
}
