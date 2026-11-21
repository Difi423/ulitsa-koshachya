import { renderCards } from './data.js';

export function matchesFilters(pet, filters) {
    const normalize = text => text.toLocaleLowerCase('ru-RU').replaceAll('ё', 'е');
    const haystack = normalize(`${pet.name} ${pet.short} ${pet.trait}`);
    if (filters.query && !haystack.includes(normalize(filters.query.trim()))) return false;
    if (filters.sex !== 'all' && pet.sex !== filters.sex) return false;
    if (filters.age === 'kitten' && pet.ageMonths >= 12) return false;
    if (filters.age === 'adult' && (pet.ageMonths < 12 || pet.ageMonths > 60)) return false;
    if (filters.age === 'senior' && pet.ageMonths <= 60) return false;
    if (filters.character !== 'all' && !pet.temperament.includes(filters.character)) return false;
    return true;
}

export function selectPets(pets, filters) {
    const result = pets.filter(pet => matchesFilters(pet, filters));
    const compareNames = (a, b) => a.name.localeCompare(b.name, 'ru');
    if (filters.sort === 'name') result.sort(compareNames);
    if (filters.sort === 'age-asc') {
        result.sort((a, b) => a.ageMonths - b.ageMonths || compareNames(a, b));
    }
    if (filters.sort === 'age-desc') {
        result.sort((a, b) => b.ageMonths - a.ageMonths || compareNames(a, b));
    }
    return result;
}

export function initCatalog(pets) {
    const form = document.querySelector('#catalog-filters');
    const grid = document.querySelector('#catalog-grid');
    const count = document.querySelector('#catalog-count');
    const empty = document.querySelector('#catalog-empty');
    const apply = form.querySelector('[type="submit"]');
    form.noValidate = true;

    function updateCatalog() {
        const values = new FormData(form);
        const selected = selectPets(pets, Object.fromEntries(values));
        renderCards(grid, selected);
        count.textContent = `Найдено: ${selected.length} из ${pets.length}`;
        empty.hidden = selected.length !== 0;
    }

    form.addEventListener('submit', event => {
        event.preventDefault();
        updateCatalog();
    });
    form.addEventListener('change', updateCatalog);
    form.querySelector('[name="query"]').addEventListener('input', updateCatalog);
    // Сначала браузер сбрасывает значения полей, затем читаем их заново.
    form.addEventListener('reset', () => setTimeout(updateCatalog, 0));
    apply.disabled = false;
    updateCatalog();
}
