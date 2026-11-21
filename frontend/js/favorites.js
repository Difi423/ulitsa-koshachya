const KEY = 'ulitsaKoshachya.favorites.v1';
let available = true;
let selected = read();

function read() {
    let raw;
    try {
        raw = window.localStorage.getItem(KEY);
    } catch {
        available = false;
        return new Set();
    }
    try {
        const value=JSON.parse(raw || '[]');
        return new Set(Array.isArray(value) ? value.filter(id => Number.isSafeInteger(id) && id>0).slice(0,100) : []);
    } catch {return new Set();}
}

export function favoriteIds() { return [...selected]; }
export function favoritesPersist() { return available; }

export function setFavorites(ids) {
    selected = new Set(ids.filter(id => Number.isSafeInteger(id) && id > 0).slice(0,100));
    try { window.localStorage.setItem(KEY,JSON.stringify([...selected]));available=true; }
    catch { available = false; }
    window.dispatchEvent(new Event('favoriteschange'));
}

function refresh(button) {
    const saved = selected.has(Number(button.dataset.favoriteId));
    button.setAttribute('aria-pressed',String(saved));
    button.setAttribute('aria-label',`${saved ? 'Убрать из избранного' : 'Добавить в избранное'}: ${button.dataset.favoriteName}`);
    button.title = saved ? 'Убрать из избранного' : 'Добавить в избранное';
    button.textContent = (saved ? '♥' : '♡') + (button.dataset.favoriteText ? (saved ? ' В избранном' : ' В избранное') : '');
}

export function favoriteButton(pet, text = false) {
    const button = document.createElement('button');
    button.type = 'button'; button.className = `favorite-button${text ? ' favorite-inline' : ''}`;
    button.dataset.favoriteId = String(pet.id); button.dataset.favoriteName = pet.name;
    if (text) button.dataset.favoriteText = '1';
    refresh(button);
    button.addEventListener('click',() => {
        if (!selected.has(pet.id) && selected.size >= 100) {
            document.querySelector('#favorites-announcement').textContent = 'В избранном уже 100 питомцев.';
            return;
        }
        const wasSaved = selected.has(pet.id);
        setFavorites(wasSaved ? favoriteIds().filter(id => id !== pet.id) : [...favoriteIds(),pet.id]);
        const announcement = document.querySelector('#favorites-announcement');
        if (announcement) announcement.textContent = `${pet.name}: ${wasSaved ? 'убран из избранного' : 'добавлен в избранное'}.`;
    });
    return button;
}

export function initFavorites() {
    if (!document.querySelector('#favorites-announcement')) {
        const status = document.createElement('p');
        status.id = 'favorites-announcement'; status.className = 'visually-hidden';status.setAttribute('role','status');
        document.body.append(status);
    }
    const update = () => {
        document.querySelectorAll('[data-favorite-id]').forEach(refresh);
        document.querySelectorAll('[data-favorite-count]').forEach(node => { node.textContent = String(selected.size); });
    };
    update(); window.addEventListener('favoriteschange',update);
    window.addEventListener('storage',event => {
        if (event.key === KEY || event.key === null) {
            selected = read(); window.dispatchEvent(new Event('favoriteschange'));
        }
    });
}
