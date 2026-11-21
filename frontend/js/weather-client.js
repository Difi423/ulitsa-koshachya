import { fetchJSON } from './data.js';

const DIRECT_URL = 'https://api.open-meteo.com/v1/forecast?' + new URLSearchParams({
    latitude: '59.94', longitude: '30.31',
    daily: 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max',
    forecast_days: '16', timezone: 'Europe/Moscow',
});

export async function requestForecast(signal) {
    let response;
    try {
        // Основной путь: браузер обращается к своему серверу.
        response = await fetch('/api/weather', { signal, cache: 'no-store' });
    } catch (error) {
        if (signal.aborted) throw error;
        return requestDirect(signal);
    }
    const contentType = response.headers.get('Content-Type') || '';
    if (response.status === 404 || response.status === 405 ||
        (response.ok && !contentType.includes('application/json'))) {
        // В Live Preview нет Python-обработчика. Сохраняем прямой запрос,
        // но при его отказе подсказываем, как включить основной путь.
        return requestDirect(signal);
    }
    if (!response.ok) {
        throw new Error('Источники погоды сейчас недоступны. Попробуйте позже.');
    }
    return response.json();
}

async function requestDirect(signal) {
    try {
        return await fetchJSON(DIRECT_URL, signal);
    } catch (error) {
        if (signal.aborted) throw error;
        throw new Error('Не удалось получить прогноз напрямую. Запустите сайт через start.bat и повторите попытку.');
    }
}

export function withDeadline(operation, controller, timeoutMs = 16000) {
    let timer;
    let onAbort;
    const interrupted = new Promise((resolve, reject) => {
        onAbort = () => reject(new DOMException('Запрос отменён', 'AbortError'));
        if (controller.signal.aborted) {
            onAbort();
            return;
        }
        controller.signal.addEventListener('abort', onAbort, { once: true });
        timer = setTimeout(() => {
            // Завершаем ожидание сами, даже если fetch не реагирует на abort.
            reject(new DOMException('Истекло время ожидания', 'TimeoutError'));
            controller.abort();
        }, timeoutMs);
    });
    const request = Promise.resolve().then(() => {
        if (controller.signal.aborted) throw new DOMException('Запрос отменён', 'AbortError');
        return operation(controller.signal);
    });
    return Promise.race([request, interrupted]).finally(() => {
        clearTimeout(timer);
        controller.signal.removeEventListener('abort', onAbort);
    });
}
