import { apiRequest } from './api.js';
import { favoriteButton } from './favorites.js';

const IMAGE_PATH = /^(?:images\/(?:pets\/)?[a-z0-9-]+\.(?:jpg|png|webp)|media\/[a-f0-9]{32}\.webp)$/;

// FastAPI читает SQLite и возвращает записи в JSON.
export const PETS_URL = '/api/pets';

let petsPromise = null;

export async function fetchJSON(url, signal) {
    const response = await fetch(url, { signal, cache: 'no-store' });
    // fetch не считает ответы 404 и 500 сетевой ошибкой: проверяем статус сами.
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }
    return response.json();
}

export function validatePets(data) {
    if (!Array.isArray(data)) {
        throw new Error('Ожидался список питомцев');
    }
    const slugs = new Set();
    for (const pet of data) {
        if (!pet || typeof pet.slug !== 'string' ||
            !/^[a-z0-9-]+$/.test(pet.slug) || slugs.has(pet.slug)) {
            throw new Error('Некорректная или повторяющаяся кличка в адресе');
        }
        slugs.add(pet.slug);
        const fields = ['name', 'age', 'sexLabel', 'trait', 'color', 'short',
            'story', 'home', 'care', 'image', 'alt'];
        if (!fields.every(key => typeof pet[key] === 'string' && pet[key].trim())) {
            throw new Error('Неполная карточка питомца');
        }
        if (!Number.isInteger(pet.id) || pet.id < 1 || typeof pet.featured !== 'boolean' ||
            !Number.isInteger(pet.ageMonths) || pet.ageMonths < 0 ||
            !['male', 'female'].includes(pet.sex) || !Array.isArray(pet.temperament) ||
            !pet.temperament.every(tag => ['calm', 'social', 'playful'].includes(tag)) ||
            !IMAGE_PATH.test(pet.image) ||
            !['available', 'reserved', 'adopted', 'archived'].includes(pet.status)) {
            throw new Error('Некорректные характеристики питомца');
        }
        if (pet.photos && (!Array.isArray(pet.photos) || !pet.photos.every(photo => IMAGE_PATH.test(photo.image) && typeof photo.alt === 'string'))) {
            throw new Error('Некорректная галерея питомца');
        }
    }
    return data;
}

export function loadPets() {
    // Несколько блоков на одной странице используют один и тот же запрос.
    if (!petsPromise) {
        petsPromise = apiRequest(PETS_URL)
            .then(validatePets)
            .catch(error => {
                petsPromise = null; // Повторная попытка после ошибки разрешена.
                throw error;
            });
    }
    return petsPromise;
}

export async function loadPet({ id, slug }) {
    const url = id ? `/api/pets/${encodeURIComponent(id)}` : `/api/pets/slug/${encodeURIComponent(slug)}`;
    const pet = await apiRequest(url);
    validatePets([pet]);
    return pet;
}

export function createElement(tag, className = '', text = '') {
    const element = document.createElement(tag);
    if (className) element.className = className;
    // Содержимое из данных и форм добавляем как текст, а не как HTML.
    if (text) element.textContent = text;
    return element;
}

export function createPetCard(pet) {
    const card = createElement('article', 'pet-card');
    card.dataset.pet = pet.slug;
    const photo = createElement('img');
    photo.src = pet.image;
    photo.alt = pet.alt;
    photo.width = 640;
    photo.height = 640;
    photo.loading = 'lazy';
    const visual = createElement('div','pet-card-visual');
    const photoLink = createElement('a');photoLink.href = `pet.html?id=${pet.id}`;
    photoLink.setAttribute('aria-label',`Подробнее: ${pet.name}`);photoLink.append(photo);
    visual.append(photoLink,favoriteButton(pet));
    const body = createElement('div', 'pet-card-body');
    body.append(
        createElement('p', 'pet-meta', `${pet.sexLabel} · ${pet.age}`),
        createElement('h3', '', pet.name),
        createElement('p', '', pet.short),
    );
    if (pet.status !== 'available') body.append(createElement('span', 'status-badge', pet.statusLabel));
    const link = createElement('a', 'card-link', 'Подробнее о питомце');
    link.href = `pet.html?id=${pet.id}`;
    link.append(createElement('span', 'visually-hidden', ` ${pet.name}`));
    const arrow = createElement('span', '', ' →');
    arrow.setAttribute('aria-hidden', 'true');
    link.append(arrow);
    body.append(link);
    card.append(visual, body);
    return card;
}

export function renderCards(container, pets) {
    container.replaceChildren(...pets.map(createPetCard));
}

export function updatePetProfile(article, pet) {
    article.querySelector('h1').textContent = pet.name;
    article.querySelector('.lead').textContent = pet.short;
    const photo = article.querySelector('.profile-photo');
    photo.src = pet.image;
    photo.alt = pet.alt;
    const facts = [pet.age, pet.sexLabel, pet.trait, pet.color];
    article.querySelectorAll('.pet-facts dd').forEach((dd, index) => {
        dd.textContent = facts[index];
    });
    for (const [heading, key] of [['history-title', 'story'], ['home-title', 'home'], ['care-title', 'care']]) {
        article.querySelector(`#${heading}`).parentElement.querySelector('p').textContent = pet[key];
    }
    article.querySelector('.eyebrow').textContent = pet.statusLabel;
    const button = article.querySelector('.profile-info a.button');
    button.textContent = pet.status === 'available' ? 'Записаться на знакомство' : pet.statusLabel;
    if (pet.status === 'available') {
        button.href = `application.html?pet=${pet.slug}`;
        button.removeAttribute('aria-disabled');
    } else {
        button.removeAttribute('href');
        button.setAttribute('aria-disabled', 'true');
    }
    article.querySelector('.profile-info .small-text').textContent = pet.status === 'available'
        ? 'Питомец будет выбран в заявке автоматически.' : 'Сейчас новые заявки на знакомство не принимаются.';
    article.querySelector('.favorite-inline')?.remove();
    article.querySelector('.profile-info').append(favoriteButton(pet,true));
    let gallery = article.querySelector('.profile-gallery');
    if (!gallery) {
        gallery = createElement('div','profile-gallery');photo.replaceWith(gallery);gallery.append(photo);
    }
    gallery.querySelector('.gallery-thumbnails')?.remove();
    const photos = pet.photos?.length ? pet.photos : [{image:pet.image,alt:pet.alt}];
    if (photos.length > 1) {
        const thumbnails = createElement('div','gallery-thumbnails');thumbnails.setAttribute('aria-label','Фотографии питомца');
        photos.forEach((item,index) => {
            const control = createElement('button','gallery-thumbnail');control.type = 'button';
            control.setAttribute('aria-label',`Фото ${index+1}: ${item.alt}`);
            control.setAttribute('aria-pressed',String(item.image === pet.image));
            const thumbnail = createElement('img');thumbnail.src=item.image;thumbnail.alt='';thumbnail.width=72;thumbnail.height=72;
            control.append(thumbnail);
            control.addEventListener('click',() => {
                photo.src=item.image;photo.alt=item.alt;
                thumbnails.querySelectorAll('button').forEach(other => other.setAttribute('aria-pressed',String(other===control)));
            });
            thumbnails.append(control);
        });
        gallery.append(thumbnails);
    }
    article.querySelector('#adoption-story')?.remove();
    if (pet.status === 'adopted') {
        const story = createElement('section','adoption-story');story.id='adoption-story';
        story.append(createElement('h2','','Теперь дома'),createElement('p','user-text',pet.adoptionStory || pet.short));
        if (pet.adoptedAt) story.append(createElement('p','small-text',`Дома с ${formatDate(pet.adoptedAt)}`));
        article.querySelector('.profile-story').prepend(story);
    }
    article.closest('main').querySelector('.breadcrumbs span:last-child').textContent = pet.name;
    document.title = `${pet.name} — Улица Кошачья`;
    document.querySelector('meta[name="description"]').content = pet.short;
}

export function formatDate(day, options = {}) {
    return new Intl.DateTimeFormat('ru-RU',{timeZone:'Europe/Moscow',day:'numeric',month:'long',year:'numeric',...options})
        .format(new Date(day+'T12:00:00+03:00'));
}
