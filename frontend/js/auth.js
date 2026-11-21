import { apiRequest, getSession, adminLoginLink } from './api.js';
import { createElement } from './data.js';

export async function initAdminNav() {
    const bar = document.querySelector('#admin-account-nav');
    if (!bar) return;
    try {
        const { user } = await getSession();
        if (user?.role !== 'admin') return;
        const logout = createElement('button', 'text-button', 'Выйти');
        logout.type = 'button';
        logout.addEventListener('click', async () => {
            logout.disabled = true;
            try {
                await apiRequest('/api/auth/logout', { method: 'POST', body: {} });
                location.assign(adminLoginLink());
            } catch (error) {
                logout.disabled = false;
                document.querySelector('#admin-status').textContent = error.message;
            }
        });
        bar.replaceChildren(createElement('span', '', `Куратор: ${user.name}`), logout);
    } catch { /* Ошибку и повтор загрузки показывает основной экран админки. */ }
}
