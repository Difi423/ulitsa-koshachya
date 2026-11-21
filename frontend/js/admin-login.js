import { apiRequest, getSession, setSession } from './api.js';
import { createElement } from './data.js';
import { bindValidation, validateLogin } from './validation.js';

export async function initAdminLogin() {
    const form = document.querySelector('#admin-login-form');
    if (!form) return;
    const status = document.querySelector('#login-status');
    try {
        const { user } = await getSession();
        if (user?.role === 'admin') { location.replace('admin.html'); return; }
        status.textContent = '';
        bindValidation(form, {
            'login-username': validateLogin,
            'login-password': value => value.length === 0 ? 'Введите пароль.'
                : value.length > 128 ? 'Пароль слишком длинный (максимум 128 символов).' : '',
        }, async values => {
            const data = await apiRequest('/api/auth/login', { method: 'POST', body: values });
            setSession(data);
            location.replace('admin.html');
        });
    } catch (error) {
        status.textContent = error.message;
        const retry = createElement('button', 'button button-secondary', 'Повторить');
        retry.type = 'button';
        retry.addEventListener('click', () => location.reload());
        status.append(document.createTextNode(' '), retry);
    }
}
