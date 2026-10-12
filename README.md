# Учёт посещаемости студентов

Веб-сервис (Django) и Telegram-бот для учёта посещаемости. Подробное описание — `kpo_project.md`.

## Запуск

Запуск (Linux): 
python3 -m venv venv && source venv/bin/activate && pip install -r requirements-dev.txt && python manage.py migrate && python manage.py runserver
Запуск (Windows): py -3.13 -m venv venv
venv\Scripts\python.exe -m pip install -r requirements-dev.txt
venv\Scripts\python.exe manage.py migrate
venv\Scripts\python.exe manage.py runserver
