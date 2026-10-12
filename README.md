# Учёт посещаемости студентов

Веб-сервис (Django) и Telegram-бот для учёта посещаемости. Подробное описание — `kpo_project.md`.

## Запуск

Запуск (Windows): py -3.13 -m venv venv
venv\Scripts\python.exe -m pip install -r requirements-dev.txt
venv\Scripts\python.exe manage.py migrate
venv\Scripts\python.exe manage.py runserver