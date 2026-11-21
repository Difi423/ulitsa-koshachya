import { createElement } from './data.js';

function formatVisit(item) {
    const day = new Intl.DateTimeFormat('ru-RU', {
        day: 'numeric', month: 'long', year: 'numeric', timeZone: 'Europe/Moscow',
    }).format(new Date(`${item.visit_date}T12:00:00+03:00`));
    const time = { '12-14': '12:00–14:00', '14-16': '14:00–16:00', '16-18': '16:00–18:00' }[item.visit_time];
    return `${day}, ${time} (МСК)`;
}

export function applicationCard(item) {
    const card = createElement('article', 'record-card');
    const heading = createElement('div', 'record-heading');
    heading.append(createElement('h3', '', `№${item.id} · ${item.pet_name}`),
        createElement('span', `status-badge status-${item.status}`, item.statusLabel));
    card.append(heading, createElement('p', '', formatVisit(item)));
    if (item.comment) card.append(createElement('p', 'user-text', item.comment));
    if (item.admin_note) card.append(createElement('p', 'curator-note', `Заметка: ${item.admin_note}`));
    return card;
}

