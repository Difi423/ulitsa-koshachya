"""Галереи и нормализованные изображения. Исходные имена не используются как пути."""
from datetime import datetime
from io import BytesIO
from pathlib import Path
import uuid

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError

from .database import ROOT
from .models import MOSCOW

FILE_LIMIT = 6 * 1024 * 1024
UPLOAD_LIMIT = 49 * 1024 * 1024


def media_exists(image, directory):
    path = directory / image.split('/')[-1] if image.startswith('media/') else ROOT / 'frontend' / image
    return path.is_file() and not path.is_symlink()


def save_pet_details(db, pet_id, body, directory, previous=None):
    photos = ([photo.model_dump() for photo in body.photos] if body.photos is not None else
              [dict(row) for row in db.execute('SELECT image,alt FROM pet_photos WHERE pet_id=? ORDER BY position,id', (pet_id,))])
    if not any(photo['image'] == body.image for photo in photos):
        photos.insert(0, {'image': body.image, 'alt': body.alt})
    if len(photos) > 12 or any(not media_exists(photo['image'], directory) for photo in photos):
        raise HTTPException(422, 'Выберите до 12 существующих фотографий. Сначала загрузите новые файлы.')
    for photo in photos:
        photo['alt'] = body.alt if photo['image'] == body.image else (photo['alt'] or body.alt)
    adopted = body.adoptedAt if 'adoptedAt' in body.model_fields_set or previous is None else previous['adopted_at']
    adoption_story = body.adoptionStory if 'adoptionStory' in body.model_fields_set or previous is None else previous['adoption_story']
    if body.status == 'adopted' and not adopted and (previous is None or previous['status'] != 'adopted'):
        adopted = datetime.now(MOSCOW).date().isoformat()
    db.execute('UPDATE pets SET adoption_story=?,adopted_at=? WHERE id=?', (adoption_story, adopted, pet_id))
    db.execute('DELETE FROM pet_photos WHERE pet_id=?', (pet_id,))
    db.executemany('INSERT INTO pet_photos(pet_id,image,alt,position) VALUES (?,?,?,?)',
                   [(pet_id, photo['image'], photo['alt'], index) for index, photo in enumerate(photos)])


async def upload_images(files, directory):
    if not 1 <= len(files) <= 8:
        raise HTTPException(422, 'Выберите от 1 до 8 фотографий за одну загрузку.')
    saved, result = [], []
    try:
        for file in files:
            raw = await file.read(FILE_LIMIT + 1)
            if not raw or len(raw) > FILE_LIMIT:
                raise HTTPException(413, 'Каждое фото должно быть непустым и не больше 6 МБ.')
            try:
                with Image.open(BytesIO(raw)) as original:
                    if original.format not in ('JPEG', 'PNG', 'WEBP'):
                        raise ValueError('format')
                    if original.width * original.height > 20_000_000 or max(original.size) > 10000:
                        raise HTTPException(413, 'Фотография слишком большая: максимум 20 мегапикселей.')
                    original.load()
                    normalized = ImageOps.exif_transpose(original)
                    normalized = normalized.convert('RGBA' if 'A' in normalized.getbands() or 'transparency' in normalized.info else 'RGB')
                    normalized.thumbnail((1600,1600), Image.Resampling.LANCZOS)
                    name = uuid.uuid4().hex + '.webp'
                    temporary = directory / (name + '.tmp')
                    final = directory / name
                    try:
                        normalized.save(temporary, 'WEBP', quality=88, method=4, exif=b'')
                        temporary.replace(final)
                    finally:
                        temporary.unlink(missing_ok=True)
                    saved.append(final)
                    label = Path(file.filename or 'Фото').stem[:160].strip() or 'Фотография питомца'
                    result.append({'image':'media/' + name, 'alt':label, 'width':normalized.width,
                                   'height':normalized.height, 'originalName':(file.filename or 'Фото')[:200]})
            except HTTPException:
                raise
            except (UnidentifiedImageError, ValueError, OSError, Image.DecompressionBombError) as exception:
                raise HTTPException(422, 'Не удалось прочитать фото. Поддерживаются настоящие JPEG, PNG и WebP.') from exception
    except Exception:
        for path in saved:
            path.unlink(missing_ok=True)
        raise
    finally:
        for file in files:
            await file.close()
    return result
