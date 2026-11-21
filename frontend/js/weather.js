import { createElement } from './data.js';
import { moscowToday, isISODate } from './validation.js';
import { requestForecast, withDeadline } from './weather-client.js';

// Прогноз для центра Петербурга, а не координаты пользователя.
const DESCRIPTION = {
    0: 'Ясно', 1: 'Преимущественно ясно', 2: 'Переменная облачность', 3: 'Пасмурно',
    45: 'Туман', 48: 'Туман с изморозью',
    51: 'Слабая морось', 53: 'Морось', 55: 'Сильная морось',
    56: 'Замерзающая морось', 57: 'Сильная замерзающая морось',
    61: 'Небольшой дождь', 63: 'Дождь', 65: 'Сильный дождь',
    66: 'Ледяной дождь', 67: 'Сильный ледяной дождь',
    71: 'Небольшой снег', 73: 'Снег', 75: 'Сильный снег', 77: 'Снежные зёрна',
    80: 'Небольшие ливни', 81: 'Ливни', 82: 'Сильные ливни',
    85: 'Небольшие снежные ливни', 86: 'Сильные снежные ливни',
    95: 'Гроза', 96: 'Гроза с градом', 99: 'Гроза с сильным градом',
};

export function weatherDescription(code) {
    return DESCRIPTION[code] || 'Описание погодных условий недоступно';
}

export function forecastDateAllowed(date, today = moscowToday()) {
    if (!isISODate(date)) return false;
    const lastDay = new Date(`${today}T12:00:00Z`);
    lastDay.setUTCDate(lastDay.getUTCDate() + 15);
    return date >= today && date <= lastDay.toISOString().slice(0, 10);
}

export function validateForecast(data) {
    const daily = data?.daily;
    const keys = ['weather_code', 'temperature_2m_min', 'temperature_2m_max',
        'precipitation_probability_max'];
    if (!daily || !Array.isArray(daily.time) || daily.time.length === 0 ||
        !daily.time.every(isISODate) ||
        !keys.every(key => Array.isArray(daily[key]) && daily[key].length === daily.time.length)) {
        throw new Error('Некорректный ответ погодного API');
    }
    const source = data.source?.id === 'met-no'
        ? { id: 'met-no', name: 'MET Norway', url: 'https://www.met.no/' }
        : { id: 'open-meteo', name: 'Open-Meteo', url: 'https://open-meteo.com/' };
    return { ...daily, source };
}

export function initWeather() {
    const panel = document.querySelector('#visit-weather');
    if (!panel) return;
    const dateInput = document.querySelector('#visit-date');
    const status = document.querySelector('#weather-status');
    const details = document.querySelector('#weather-details');
    const retry = document.querySelector('#weather-retry');
    const source = panel.querySelector('.weather-source');
    let forecast = null;
    let loadedAt = 0;
    let loadedToday = '';
    let controller = null;
    let requestNumber = 0;

    function showDay(day) {
        const credit = createElement('a', '', forecast.source.name);
        credit.href = forecast.source.url;
        credit.target = '_blank';
        credit.rel = 'noopener noreferrer';
        const license = createElement('a', '', 'CC BY 4.0');
        license.href = 'https://creativecommons.org/licenses/by/4.0/';
        license.target = '_blank';
        license.rel = 'noopener noreferrer';
        source.replaceChildren(document.createTextNode('Данные: '), credit,
            document.createTextNode(', '), license, document.createTextNode('. Прогноз может меняться.'));
        if (forecast.source.id === 'met-no') {
            source.append(document.createTextNode(' Температура — диапазон по доступным срокам прогноза.'));
        }
        const index = forecast.time.indexOf(day);
        if (index === -1) {
            details.hidden = true;
            status.textContent = 'У выбранного источника пока нет прогноза на этот день. Посмотрите его ближе к визиту.';
            return;
        }
        const minimum = forecast.temperature_2m_min[index];
        const maximum = forecast.temperature_2m_max[index];
        const code = forecast.weather_code[index];
        if (![minimum, maximum].every(Number.isFinite)) {
            throw new Error('На выбранный день пока нет температуры. Попробуйте другую дату.');
        }
        const formatted = new Intl.DateTimeFormat('ru-RU', {
            timeZone: 'Europe/Moscow', weekday: 'long', day: 'numeric', month: 'long',
        }).format(new Date(`${day}T12:00:00+03:00`));
        document.querySelector('#weather-date').textContent = formatted;
        const description = forecast.description?.[index];
        document.querySelector('#weather-summary').textContent = typeof description === 'string'
            ? description : weatherDescription(code);
        document.querySelector('#weather-temperature').textContent = `${minimum}…${maximum} °C`;
        const rain = forecast.precipitation_probability_max[index];
        document.querySelector('#weather-rain').textContent = Number.isFinite(rain) ? `${rain}%` : 'Нет данных';
        status.textContent = 'Прогноз загружен.';
        details.hidden = false;
    }

    async function updateWeather(force = false) {
        const currentRequest = ++requestNumber;
        controller?.abort();
        details.hidden = true;
        const day = dateInput.value || moscowToday();
        if (!forecastDateAllowed(day)) {
            status.textContent = 'Прогноз доступен на ближайшие 16 дней. Для выбранной даты посмотрите его ближе к визиту.';
            panel.setAttribute('aria-busy', 'false');
            retry.disabled = false;
            return;
        }
        const activeController = new AbortController();
        controller = activeController;
        retry.disabled = true;
        panel.setAttribute('aria-busy', 'true');
        status.textContent = 'Загружаем прогноз…';
        try {
            const stale = Date.now() - loadedAt > 10 * 60 * 1000 || loadedToday !== moscowToday();
            if (force || !forecast || stale) {
                const data = await withDeadline(requestForecast, activeController);
                if (currentRequest !== requestNumber) return;
                forecast = validateForecast(data);
                loadedAt = Date.now();
                loadedToday = moscowToday();
            }
            if (currentRequest !== requestNumber) return;
            showDay(day);
        } catch (error) {
            if (currentRequest !== requestNumber) return;
            status.textContent = ['AbortError', 'TimeoutError'].includes(error.name)
                ? 'Прогноз не получен за 16 секунд. Проверьте, что сайт запущен через start.bat, и попробуйте ещё раз.'
                : (error.message || 'Не удалось загрузить прогноз. Проверьте подключение и попробуйте ещё раз.');
        } finally {
            if (currentRequest === requestNumber) {
                panel.setAttribute('aria-busy', 'false');
                retry.disabled = false;
            }
        }
    }

    dateInput.addEventListener('change', () => updateWeather());
    dateInput.form.addEventListener('reset', () => setTimeout(() => updateWeather(), 0));
    retry.addEventListener('click', () => updateWeather(true));
    updateWeather();
}
