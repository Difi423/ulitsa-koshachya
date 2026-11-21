// Необязательная проверка браузерного хранилища: node --test tests/test_favorites.mjs
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const source=await readFile(new URL('../frontend/js/favorites.js',import.meta.url),'utf8');
let version=0;
const KEY='ulitsaKoshachya.favorites.v1';
function storage(initial=null) {
    const values=new Map(initial===null ? [] : [[KEY,initial]]);
    return {getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value)};
}
async function open(store) {
    globalThis.window=Object.assign(new EventTarget(),{localStorage:store});
    return import('data:text/javascript;base64,'+Buffer.from(source).toString('base64')+'#'+version++);
}

test('выбор сохраняется при повторном открытии и удаление тоже сохраняется',async()=>{
    const store=storage();let page=await open(store);
    page.setFavorites([1,13]);page=await open(store);assert.deepEqual(page.favoriteIds(),[1,13]);
    page.setFavorites([13]);page=await open(store);assert.deepEqual(page.favoriteIds(),[13]);
});
test('повреждённое содержимое не ломает дальнейшее сохранение',async()=>{
    const store=storage('{bad json');const page=await open(store);
    assert.deepEqual(page.favoriteIds(),[]);assert.equal(page.favoritesPersist(),true);
    page.setFavorites([2]);assert.deepEqual((await open(store)).favoriteIds(),[2]);
});
test('при запрете хранилища выбор работает в памяти и восстанавливает сохранение после разрешения',async()=>{
    const store={getItem(){throw Error('blocked');},setItem(){throw Error('blocked');}};
    const page=await open(store);page.setFavorites([3]);
    assert.deepEqual(page.favoriteIds(),[3]);assert.equal(page.favoritesPersist(),false);
    window.localStorage=storage();page.setFavorites([3,4]);
    assert.equal(page.favoritesPersist(),true);assert.deepEqual((await open(window.localStorage)).favoriteIds(),[3,4]);
});
test('посторонние значения и слишком большой список не попадают в избранное',async()=>{
    let page=await open(storage('[1,1,-2,"3",null,4]'));assert.deepEqual(page.favoriteIds(),[1,4]);
    page.setFavorites(Array.from({length:120},(_,i)=>i+1));
    page=await open(window.localStorage);assert.equal(page.favoriteIds().length,100);
});
