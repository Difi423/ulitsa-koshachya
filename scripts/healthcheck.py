"""Проверка HTTP и доступности схемы базы. Нужна Docker HEALTHCHECK."""
import json
import os
import sys
from urllib.request import urlopen

try:
    port = int(os.environ.get('PORT') or os.environ.get('SHELTER_PORT') or 8000)
    with urlopen(f'http://127.0.0.1:{port}/api/health', timeout=3) as response:
        healthy = response.status == 200 and json.load(response) == {'status': 'ok'}
except Exception:
    healthy = False
sys.exit(0 if healthy else 1)
