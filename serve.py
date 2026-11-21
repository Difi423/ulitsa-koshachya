"""Неинтерактивный запуск готового окружения, в том числе в Docker."""
import os
import uvicorn
from backend.config import Settings


def main():
    os.umask(0o077)
    settings = Settings.from_env()
    uvicorn.run('backend.app:app', host=settings.host, port=settings.port, workers=1,
                proxy_headers=bool(settings.trusted_proxies),
                forwarded_allow_ips=settings.trusted_proxies, server_header=False,
                log_level=settings.log_level, timeout_keep_alive=5)


if __name__ == '__main__':
    main()
