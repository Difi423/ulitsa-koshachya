import { createElement,createPetCard,renderCards,formatDate } from './data.js';
import { favoriteIds,setFavorites,favoritesPersist } from './favorites.js';

let currentPets = [];

function adoptedCards(container,pets) {
    container.replaceChildren();
    for (const pet of pets) {
        const card = createPetCard(pet);
        const paragraphs = card.querySelectorAll('.pet-card-body > p');
        paragraphs[1].textContent = pet.adoptionStory || pet.short;
        if (pet.adoptedAt) card.querySelector('.pet-card-body').append(createElement('p','small-text',`Дома с ${formatDate(pet.adoptedAt)}`));
        container.append(card);
    }
    if (!pets.length) container.append(createElement('p','empty-state','Здесь будут истории питомцев, которые нашли своих людей.'));
}

function renderFavorites() {
    const container = document.querySelector('#favorites-grid');
    if (!container) return;
    const ids = favoriteIds();
    const pets = currentPets.filter(pet => ids.includes(pet.id));
    renderCards(container,pets);
    document.querySelector('#favorites-empty').hidden = pets.length > 0;
    document.querySelector('#favorites-count').textContent = `Выбрано питомцев: ${pets.length}`;
    const stale = ids.filter(id => !currentPets.some(pet => pet.id === id));
    document.querySelector('#favorites-unavailable').hidden = stale.length === 0;
    document.querySelector('#favorites-unavailable').textContent = stale.length
        ? `Некоторые выбранные питомцы сейчас недоступны: ${stale.length}.` : '';
    document.querySelector('#favorites-cleanup').hidden = stale.length === 0;
    document.querySelector('#favorites-clear').disabled = ids.length === 0;
    document.querySelector('#favorites-storage').hidden = favoritesPersist();
}

export function initPublicPages(pets) {
    currentPets = pets;
    const adopted = pets.filter(pet => pet.status === 'adopted').sort((a,b) => b.adoptedAt.localeCompare(a.adoptedAt) || a.id-b.id);
    const full = document.querySelector('#adopted-grid');
    if (full) {
        adoptedCards(full,adopted);
        document.querySelector('#adopted-count').textContent = `Питомцев дома: ${adopted.length}`;
    }
    const preview = document.querySelector('#adopted-preview');
    if (preview) adoptedCards(preview,adopted.slice(0,3));
    if (document.querySelector('#favorites-grid')) {
        renderFavorites();
        const page = document.querySelector('#favorites-grid');
        if (!page.dataset.bound) {
            page.dataset.bound = '1';
            window.addEventListener('favoriteschange',renderFavorites);
            document.querySelector('#favorites-clear').addEventListener('click',() => setFavorites([]));
            document.querySelector('#favorites-cleanup').addEventListener('click',() => setFavorites(favoriteIds().filter(id => currentPets.some(pet => pet.id === id))));
        }
    }
}
