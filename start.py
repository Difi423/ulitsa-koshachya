"""Запуск, установка зависимостей в .venv и создание администратора."""
from pathlib import Path
import argparse
import getpass
import os
import sqlite3
import subprocess
import sys
import threading
import venv
import webbrowser

ROOT = Path(__file__).resolve().parent


def prepare_environment(args):
    """Собственное окружение: глобальный Python не меняем."""
    environment = ROOT / '.venv'
    interpreter = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not interpreter.is_file():
        print('Первый запуск: создаём окружение Python…', flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    requirements = []
    for line in (ROOT / 'requirements.txt').read_text(encoding='utf-8').splitlines():
        if line and not line.startswith('#'):
            package, version = line.split('==')
            requirements.append((package.split('[')[0], version))
    check = 'import importlib.metadata as m; import sys; sys.exit(not all(m.version(n)==v for n,v in ' + repr(requirements) + '))'
    installed = subprocess.run([str(interpreter), '-c', check], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if not installed:
        print('Устанавливаем зависимости. На этом шаге нужен интернет.', flush=True)
        subprocess.run([str(interpreter), '-m', 'pip', 'install', '-r', str(ROOT / 'requirements.txt')], check=True)
    return subprocess.call([str(interpreter), str(ROOT / 'start.py'), '--serve'] + args, cwd=ROOT)


def create_admin(database):
    from backend.models import AdminAccount
    from backend.security import passwords
    from pydantic import ValidationError
    print('\nСоздание администратора. Эти данные сохраняются только в вашей локальной базе.')
    while True:
        try:
            name = input('Имя: ').strip()
            login = input('Логин для входа: ').strip()
            password = getpass.getpass('Пароль (ввод скрыт): ')
            if password != getpass.getpass('Повторите пароль: '):
                print('Пароли не совпадают. Повторите ввод.')
                continue
            user = AdminAccount(name=name, login=login, password=password)
            with database.connect() as db:
                db.execute("INSERT INTO users(name,login,password_hash,role) VALUES (?,?,?,'admin')",
                           (user.name, user.login, passwords.hash(user.password)))
            print('Администратор создан. Войдите с этим логином и паролем на сайте.\n')
            return
        except ValidationError:
            print('Проверьте имя и логин. Пароль должен быть непустым, не длиннее 128 символов.')
        except sqlite3.IntegrityError:
            print('Этот логин уже занят. Для администратора укажите другой.')


def main():
    if sys.version_info < (3, 10):
        raise SystemExit('Нужен Python версии 3.10 или новее.')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Запустить сайт «Улица Кошачья»')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--host', default='127.0.0.1', help=argparse.SUPPRESS)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--create-admin', action='store_true', help='Создать администратора в консоли')
    parser.add_argument('--no-setup', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--serve', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.serve:
        try:
            raise SystemExit(prepare_environment(sys.argv[1:]))
        except (OSError, subprocess.CalledProcessError) as error:
            print('Не удалось подготовить запуск. Проверьте доступ к интернету и сообщения выше.')
            raise SystemExit(1) from error

    from backend.app import app
    import uvicorn
    app.state.database.initialize()
    if args.create_admin:
        create_admin(app.state.database)
        return
    if not args.no_setup and not app.state.database.has_admin():
        if sys.stdin.isatty():
            print('Первый запуск: создадим учётную запись владельца приюта.')
            create_admin(app.state.database)
        else:
            print('Администратор ещё не создан. Выполните python start.py --create-admin.')
    url = f'http://127.0.0.1:{args.port}/'
    print(f'\nСайт: {url}\nОставьте это окно открытым. Остановка: Ctrl+C.', flush=True)
    if not args.no_browser:
        threading.Timer(1, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=args.host, port=args.port, proxy_headers=False)


if __name__ == '__main__':
    main()
