import { loadPets, loadPet, renderCards, updatePetProfile, createElement } from './data.js';
import { initCatalog } from './catalog.js';
import { initApplication, initFeedback } from './forms.js';
import { initWeather } from './weather.js';
import { initAdminNav } from './auth.js';
import { initAdminLogin } from './admin-login.js';
import { initAdmin } from './admin.js';
import { initFavorites } from './favorites.js';
import { initPublicPages } from './public-pages.js';

initFavorites();
initAdminNav();
initFeedback();
initWeather();
initAdminLogin();
initAdmin();

const dataStatus = document.querySelector('#data-status');
const retry = document.querySelector('#data-retry');

async function initPetData() {
    retry.hidden = true;
    dataStatus.hidden = false;
    dataStatus.textContent = 'Загружаем сведения о питомцах…';
    try {
        const profile = document.querySelector('.pet-profile');
        if (profile) {
            const id = new URLSearchParams(location.search).get('id') || profile.dataset.petId;
            const pet = await loadPet({ id, slug: profile.dataset.pet || '' });
            updatePetProfile(profile, pet);
            profile.hidden = false;
        } else {
            const pets = await loadPets();
            initPublicPages(pets);
            const featured = document.querySelector('#featured-pets');
            if (featured) {
                renderCards(featured, pets.filter(pet => pet.featured && pet.status === 'available').slice(0, 6));
                if (!featured.children.length) featured.append(createElement('p', '', 'Новых питомцев скоро добавят.'));
                const link = document.querySelector('.section-heading .text-link');
                link.textContent = `Все питомцы (${pets.filter(pet => pet.status !== 'adopted').length}) →`;
            }
            if (document.querySelector('#catalog-filters')) initCatalog(pets.filter(pet => pet.status !== 'adopted'));
            if (document.querySelector('#application-form')) await initApplication(pets);
        }
        dataStatus.textContent = '';
        dataStatus.hidden = true;
    } catch (error) {
        dataStatus.textContent = error.message || 'Не удалось получить данные с сервера.';
        retry.hidden = false;
    }
}

if (dataStatus && retry) {
    retry.addEventListener('click', initPetData);
    initPetData();
}
