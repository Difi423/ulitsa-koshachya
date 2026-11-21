export function moscowToday(now = new Date()) {
    const parts = new Intl.DateTimeFormat('en-CA', {
        timeZone: 'Europe/Moscow', year: 'numeric', month: '2-digit', day: '2-digit',
    }).formatToParts(now);
    const get = type => parts.find(part => part.type === type).value;
    return `${get('year')}-${get('month')}-${get('day')}`;
}

export function moscowMinutes(now = new Date()) {
    const parts = new Intl.DateTimeFormat('en-GB', {
        timeZone: 'Europe/Moscow', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
    }).formatToParts(now);
    return Number(parts.find(part => part.type === 'hour').value) * 60 +
        Number(parts.find(part => part.type === 'minute').value);
}

export function validateName(value) {
    const name = value.trim();
    if (name.length < 2 || name.length > 60) return 'Введите имя длиной от 2 до 60 символов.';
    if (!/^[\p{L}][\p{L}\p{M} '\u2019-]*$/u.test(name)) {
        return 'Используйте буквы, пробел, дефис или апостроф.';
    }
    return '';
}

export function validateLogin(value) {
    return /^[a-zа-яё0-9][a-zа-яё0-9_.-]{0,39}$/i.test(value.trim())
        ? '' : 'Введите логин: 1–40 букв, цифр, точек, дефисов или подчёркиваний; начните с буквы или цифры.';
}

export function normalizePhone(value) {
    const digits = value.replace(/\D/g, '');
    if (digits.length === 10) return `+7${digits}`;
    return `+7${digits.slice(1)}`;
}

export function validatePhone(value) {
    const phone = value.trim();
    const digits = phone.replace(/\D/g, '');
    if (!/^[+\d\s()-]+$/.test(phone) ||
        !(digits.length === 10 || (digits.length === 11 && /^[78]/.test(digits)))) {
        return 'Введите 10 цифр номера или 11 цифр с кодом 7 либо 8.';
    }
    return '';
}

export function validateMessage(value, minimum = 10, maximum = 2000) {
    const length = value.trim().length;
    return length < minimum || length > maximum
        ? `Введите от ${minimum} до ${maximum} символов.` : '';
}

export function isISODate(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const day = new Date(`${value}T12:00:00Z`);
    return !Number.isNaN(day.getTime()) && day.toISOString().slice(0, 10) === value;
}

export function validateVisitDate(value, now = new Date()) {
    if (!isISODate(value)) return 'Выберите корректную дату визита.';
    if (value < moscowToday(now)) return 'Дата визита не может быть в прошлом.';
    if (new Date(`${value}T12:00:00Z`).getUTCDay() === 1) {
        return 'По понедельникам приют закрыт. Выберите другой день.';
    }
    return '';
}

export function validateVisitTime(value, date, now = new Date()) {
    const startHours = { '12-14': 12, '14-16': 14, '16-18': 16 };
    if (!(value in startHours)) return 'Выберите удобное время.';
    if (date === moscowToday(now) && startHours[value] * 60 <= moscowMinutes(now)) {
        return 'Это время уже прошло. Выберите другой интервал или день.';
    }
    return '';
}

export function bindValidation(form, rules, onValid) {
    form.noValidate = true;
    const touched = new Set();
    const fields = Object.keys(rules).map(id => form.querySelector(`#${id}`));
    const result = document.querySelector(`#${form.id}-result`);

    function clearResult() {
        result.hidden = true;
        result.replaceChildren();
    }

    function showError(field, message) {
        const error = document.querySelector(`#${field.id}-error`);
        error.textContent = message;
        error.hidden = !message;
        if (message) field.setAttribute('aria-invalid', 'true');
        else field.removeAttribute('aria-invalid');
    }

    function checkField(field) {
        const value = field.type === 'checkbox' ? field.checked : field.value;
        const message = rules[field.id](value);
        showError(field, message);
        return !message;
    }

    for (const field of fields) {
        const error = document.createElement('p');
        error.id = `${field.id}-error`;
        error.className = 'field-error';
        error.hidden = true;
        // У checkbox общая подпись: ошибку размещаем после неё.
        if (field.type === 'checkbox') field.closest('label').after(error);
        else field.after(error);
        const descriptions = field.getAttribute('aria-describedby') || '';
        field.setAttribute('aria-describedby', `${descriptions} ${error.id}`.trim());
        field.addEventListener('blur', () => {
            touched.add(field.id);
            checkField(field);
        });
        const update = () => {
            clearResult();
            if (touched.has(field.id)) checkField(field);
        };
        field.addEventListener('input', update);
        field.addEventListener('change', update);
    }

    // Удаляем результат проверки и при изменении необязательного поля.
    form.addEventListener('input', clearResult);
    form.addEventListener('change', clearResult);
    form.addEventListener('submit', async event => {
        event.preventDefault();
        clearResult();
        let firstInvalid = null;
        for (const field of fields) {
            touched.add(field.id);
            if (!checkField(field) && !firstInvalid) firstInvalid = field;
        }
        if (firstInvalid) {
            firstInvalid.focus();
            return;
        }
        const values = Object.fromEntries(new FormData(form));
        const controls = [...form.elements].map(field => [field, field.disabled]);
        controls.forEach(([field]) => { field.disabled = true; });
        form.setAttribute('aria-busy', 'true');
        result.textContent = 'Сохраняем данные…';
        result.hidden = false;
        try {
            await onValid(values, result);
        } catch (error) {
            result.textContent = error.message || 'Не удалось сохранить данные. Попробуйте ещё раз.';
            let first = null;
            for (const field of fields) {
                if (error.fields?.[field.name]) {
                    showError(field, error.fields[field.name]);
                    if (!first) first = field;
                }
            }
            if (first) setTimeout(() => first.focus(), 0);
        } finally {
            controls.forEach(([field, disabled]) => { field.disabled = disabled; });
            form.setAttribute('aria-busy', 'false');
        }
    });
    form.addEventListener('reset', () => {
        touched.clear();
        for (const field of fields) showError(field, '');
        clearResult();
    });
    form.querySelector('[type="submit"]').disabled = false;
}

export function addResultLine(container, label, value) {
    const row = document.createElement('div');
    const term = document.createElement('dt');
    const definition = document.createElement('dd');
    term.textContent = label;
    definition.textContent = value;
    row.append(term, definition);
    container.append(row);
}
