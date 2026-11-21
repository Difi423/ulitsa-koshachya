import { apiRequest } from './api.js';
import { createElement } from './data.js';

export function initPhotoEditor(form) {
    let photos = [];
    const select = form.elements.image;
    const grid = document.querySelector('#pet-gallery-editor');
    const input = document.querySelector('#pet-upload-files');
    const status = document.querySelector('#pet-upload-status');
    const upload = document.querySelector('#pet-upload-button');

    function ensureOption(image,label) {
        if (![...select.options].some(option => option.value === image)) select.append(new Option(label || image.split('/').pop(),image));
    }
    function preview() {
        const photo = document.querySelector('#pet-editor-photo');
        photo.hidden = !select.value;
        if (select.value) photo.src = select.value;
    }
    function cover(photo) {
        ensureOption(photo.image);
        select.value = photo.image;
        const alt = photo.alt.length >= 5 ? photo.alt : `${form.elements.name.value || 'Питомец'}: фотография`;
        photo.alt = alt;form.elements.alt.value = alt;
        preview();render();
    }
    function control(text,action) {
        const button = createElement('button','text-button',text);button.type='button';button.addEventListener('click',action);return button;
    }
    function render() {
        grid.replaceChildren();
        document.querySelector('#pet-gallery-count').textContent = `Фото в галерее: ${photos.length} из 12`;
        photos.forEach((photo,index) => {
            const card=createElement('div','photo-editor-card');
            const image=createElement('img');image.src=photo.image;image.alt=photo.alt;image.width=120;image.height=100;
            const label=createElement('label','','Описание фото');
            const caption=createElement('input');caption.id=`photo-caption-${index}`;caption.type='text';caption.maxLength=200;caption.value=photo.alt;
            label.htmlFor=caption.id;
            caption.addEventListener('input',() => {photo.alt=caption.value;if (select.value===photo.image)form.elements.alt.value=caption.value;});
            const choose=control(select.value===photo.image ? 'Обложка ✓' : 'На обложку',() => cover(photo));
            choose.setAttribute('aria-pressed',String(select.value===photo.image));
            const actions=createElement('div','photo-editor-actions');actions.append(choose);
            if (index>0) actions.append(control('Выше',() => { [photos[index-1],photos[index]]=[photos[index],photos[index-1]];render(); }));
            actions.append(control('Убрать из галереи',() => {
                photos=photos.filter(item => item!==photo);
                if (select.value===photo.image) {
                    if (photos.length) {cover(photos[0]);return;}
                    select.value='';preview();
                }
                render();
            }));
            card.append(image,label,caption,actions);grid.append(card);
        });
    }
    select.addEventListener('change',() => {
        if (!select.value) {preview();return;}
        let photo=photos.find(item => item.image===select.value);
        if (!photo) {
            if (photos.length>=12) {status.textContent='В галерее уже 12 фото. Сначала уберите одно.';select.value=photos[0].image;preview();return;}
            photo={image:select.value,alt:form.elements.alt.value || `${form.elements.name.value || 'Питомец'}: фотография`};photos.push(photo);
        }
        cover(photo);
    });
    form.elements.alt.addEventListener('input',() => {
        const photo=photos.find(item => item.image===select.value);
        if (photo) {
            photo.alt=form.elements.alt.value;
            const index=photos.indexOf(photo);const caption=document.querySelector(`#photo-caption-${index}`);
            if (caption)caption.value=photo.alt;
        }
    });
    upload.addEventListener('click',async () => {
        const files=[...input.files];
        if (!files.length || files.length>8 || photos.length+files.length>12) {status.textContent='Выберите 1–8 файлов. В галерее может быть до 12 фото.';return;}
        if (files.some(file => file.size>6*1024*1024 || !file.size)) {status.textContent='Каждое фото должно быть непустым и не больше 6 МБ.';return;}
        const controls=[...form.elements].map(field => [field,field.disabled]);
        controls.forEach(([field]) => {field.disabled=true;});form.setAttribute('aria-busy','true');
        status.textContent='Загружаем фотографии…';
        try {
            const data=new FormData();files.forEach(file => data.append('files',file));
            const uploaded=await apiRequest('/api/admin/uploads',{method:'POST',body:data,timeoutMs:90000});
            for (const item of uploaded) {
                ensureOption(item.image,item.originalName);
                photos.push({image:item.image,alt:item.alt.length>=5 ? item.alt : `${form.elements.name.value || 'Питомец'}: фотография`});
            }
            if (!select.value && photos.length)cover(photos[0]);else render();
            input.value='';status.textContent=`Загружено фото: ${uploaded.length}. Сохраните карточку, чтобы применить галерею.`;
        } catch(error) {status.textContent=error.message;}
        finally {controls.forEach(([field,disabled]) => {field.disabled=disabled;});form.setAttribute('aria-busy','false');}
    });
    return {
        open(pet) {
            photos=(pet?.photos || (pet ? [{image:pet.image,alt:pet.alt}] : [])).map(item => ({image:item.image,alt:item.alt}));
            for (const photo of photos)ensureOption(photo.image);
            if (pet)select.value=pet.image;
            input.value='';status.textContent='';render();preview();
        },
        values() {return photos.map(photo => ({image:photo.image,alt:photo.image===select.value ? form.elements.alt.value : photo.alt}));},
    };
}
