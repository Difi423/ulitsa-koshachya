import { withDeadline } from './weather-client.js';

let session = { user: null, csrfToken: null };
let sessionPromise = null;

export function setSession(value) {
    session = value;
    sessionPromise = Promise.resolve(value);
    window.dispatchEvent(new Event('sessionchange'));
    return value;
}

export async function apiRequest(url, { method = 'GET', body, anonymous = false, timeoutMs = 16000 } = {}) {
    const controller = new AbortController();
    const headers = { Accept: 'application/json' };
    const multipart = body instanceof FormData;
    if (body !== undefined && !multipart) headers['Content-Type'] = 'application/json';
    if (!anonymous && session.csrfToken && method !== 'GET') headers['X-CSRF-Token'] = session.csrfToken;
    try {
        return await withDeadline(async signal => {
            const response = await fetch(url, {
                method, signal, headers, credentials: anonymous ? 'omit' : 'same-origin', cache: 'no-store',
                body: body === undefined ? undefined : multipart ? body : JSON.stringify(body),
            });
            let data;
            try { data = await response.json(); }
            catch { throw new Error('Сервер не вернул данные. Запустите сайт через start.bat.'); }
            if (!response.ok) {
                const error = new Error(typeof data.detail === 'string' ? data.detail : 'Не удалось выполнить запрос.');
                error.status = response.status;
                error.fields = data.fields || {};
                throw error;
            }
            return data;
        }, controller, timeoutMs);
    } catch (error) {
        if (['AbortError', 'TimeoutError'].includes(error.name)) {
            throw new Error(multipart ? 'Загрузка фото заняла слишком много времени. Обновите список фотографий перед повторной загрузкой.' : 'Сервер не ответил за 16 секунд. Если вы отправляли заявку, она могла сохраниться. Повторная отправка с тем же телефоном, питомцем, днём и временем не создаст дубль активной заявки.');
        }
        if (error instanceof TypeError) throw new Error('Нет связи с сервером. Проверьте, что окно start.bat открыто.');
        throw error;
    }
}

export async function downloadCSV(url) {
    const controller = new AbortController();
    const file = await withDeadline(async signal => {
        const response = await fetch(url, {signal,credentials:'same-origin',cache:'no-store'});
        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || 'Не удалось выгрузить заявки.');
        }
        return {blob:await response.blob(),name:response.headers.get('Content-Disposition')?.match(/filename="([a-z0-9.-]+)"/)?.[1] || 'applications.csv'};
    },controller);
    const objectURL = URL.createObjectURL(file.blob);
    const link = document.createElement('a');
    link.href = objectURL; link.download = file.name;
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(objectURL),1000);
}

export function getSession() {
    if (!sessionPromise) {
        sessionPromise = apiRequest('/api/auth/me').then(value => {
            session = value;
            return value;
        }).catch(error => { sessionPromise = null; throw error; });
    }
    return sessionPromise;
}

export function adminLoginLink() {
    return 'admin-login.html';
}
