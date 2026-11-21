"""Ограничиваем тело до разбора JSON/multipart, в том числе без Content-Length."""
import secrets
from fastapi import Request
from fastapi.responses import JSONResponse
from .media import UPLOAD_LIMIT
from .security import read_session


class RequestLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not scope['path'].startswith('/api/') or scope['method'] not in ('POST','PUT','PATCH','DELETE'):
            return await self.app(scope, receive, send)

        async def reject(message, code):
            await JSONResponse({'detail':message,'fields':{}}, status_code=code)(scope, receive, send)

        upload = scope['path'] == '/api/admin/uploads' and scope['method'] == 'POST'
        request = Request(scope)
        if upload:
            user = read_session(request)
            if user is None:
                return await reject('Войдите как администратор.', 401)
            if not secrets.compare_digest(request.headers.get('x-csrf-token',''), user['csrf_token']):
                return await reject('Обновите страницу и повторите действие.', 403)
        limit = UPLOAD_LIMIT if upload else 64 * 1024
        try:
            if int(request.headers.get('content-length') or 0) > limit:
                return await reject('Слишком большой запрос.', 413)
        except ValueError:
            return await reject('Некорректная длина запроса.', 400)
        chunks, length = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            data = message.get('body', b'')
            length += len(data)
            if length > limit:
                return await reject('Слишком большой запрос.', 413)
            chunks.append(data)
            if not message.get('more_body', False):
                break
        payload, consumed = b''.join(chunks), False

        async def replay():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {'type':'http.request','body':payload,'more_body':False}
            return await receive()

        await self.app(scope, replay, send)
