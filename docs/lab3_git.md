# ЛР3. Git и GitHub — пошаговая инструкция

Порядок повторяет «Порядок выполнения» ЛР3 из методички. 📸 — место для скриншота.
Команды выполняются во встроенном терминале VS Code (Ctrl+`) в папке проекта.
Подойдут и PowerShell, и Git Bash.

В методичке основная ветка называется `master`. Это старое имя, GitHub сейчас
создаёт `main`. Ниже используется `main`, на суть работы это не влияет.


---
328302570+CloudyPair@users.noreply.github.com

## Часть 1. GitHub: аккаунт и пустой репозиторий

1. Откройте https://github.com и **войдите в нужный аккаунт**. Если в браузере
   уже открыт другой аккаунт: аватар справа сверху → **Sign out**. Ещё проще
   открыть приватное окно: Ctrl+Shift+N в Chrome/Edge.
2. **Скрыть почту** (репозиторий публичный, а почта автора видна в каждом коммите):
   аватар → **Settings** → **Emails** → включите **Keep my email addresses private**.
   Ниже появится адрес вида `12345678+ИМЯ@users.noreply.github.com`.
   Скопируйте его, он понадобится в части 2. 📸
3. Создайте репозиторий: **+** справа сверху → **New repository**.
   - **Repository name**: например, `attendance-tracker`;
   - **Description**: «Учёт посещаемости студентов (курсовой проект ТП)»;
   - **Public**;
   - **ничего не добавляйте**: README, .gitignore и License оставьте выключенными.
     Репозиторий должен быть пустым, иначе первый push вызовет конфликт историй.
   - **Create repository**. 📸
4. На открывшейся странице выберите **HTTPS** и скопируйте ссылку
   `https://github.com/ИМЯ/attendance-tracker.git`. 📸

---

## Часть 2. Локальный репозиторий и первый коммит

```bash
git init -b main
```
📸 Появится папка `.git`. В VS Code на панели слева, во вкладке Source Control,
станут видны файлы.

**Подпись автора.** Без `--global`, то есть только для этого проекта. Так другие
проекты и другие аккаунты на этом компьютере не затронуты:
```bash
git config user.name "Имя Фамилия"
git config user.email "12345678+ИМЯ@users.noreply.github.com"
git config --list --local
```
📸 (В методичке `git config --global ...` задаёт подпись для всех репозиториев
компьютера. Нам это не подходит, потому что аккаунт отдельный.)

**Проверить, что попадёт в коммит.** В списке должны быть код, `UML/`, `docs/`,
`.gitignore`, `requirements*.txt`. Не должно быть `venv/`, `db.sqlite3`,
`__pycache__/` и методички:
```bash
git status
git add .
git status
```
📸

```bash
git commit -m "Проект учёта посещаемости: ТЗ, UML-диаграммы (ЛР2), Django-модели и каркас сервисов"
git log --oneline
```
📸

---

## Часть 3. Изменения, ветка и слияние (как требует методичка)

### 3.1 Внести изменение и зафиксировать
Создайте в корне файл `README.md`:
```markdown
# Учёт посещаемости студентов

Веб-сервис (Django) и Telegram-бот для учёта посещаемости. Подробное описание — `kpo_project.md`.

## Запуск

Запуск: см. раздел 7 в kpo_project.md
```
```bash
git add README.md
git commit -m "Добавлен README"
```

### 3.2 Создать новую ветку, изменить, зафиксировать
```bash
git checkout -b feature/readme
```
В `README.md` замените строку `Запуск: см. раздел 7 в kpo_project.md` на:
```
Запуск (Windows): py -3.13 -m venv venv; venv\Scripts\python.exe -m pip install -r requirements-dev.txt; venv\Scripts\python.exe manage.py migrate; venv\Scripts\python.exe manage.py runserver
```
```bash
git commit -am "README: команды запуска для Windows"
```
📸

### 3.3 Вернуться на main, изменить ту же строку, зафиксировать
```bash
git checkout main
```
В `README.md` замените ту же строку на:
```
Запуск (Linux): python3 -m venv venv && source venv/bin/activate && pip install -r requirements-dev.txt && python manage.py migrate && python manage.py runserver
```
```bash
git commit -am "README: команды запуска для Linux"
```

### 3.4 Слияние и конфликт
```bash
git merge feature/readme
```
Git сообщит **CONFLICT**: обе ветки поменяли одну и ту же строку. 📸
Откройте `README.md` в VS Code. Над конфликтом будут кнопки
**Accept Current / Accept Incoming / Accept Both**. Нажмите **Accept Both
Changes**: останутся обе строки, для Windows и для Linux. 📸 Сохраните файл, затем:
```bash
git add README.md
git commit -m "Слияние feature/readme: конфликт в README разрешён"
```

### 3.5 Дерево изменений (история)
```bash
git log --graph --oneline --all
```
📸 Видно, как ветка отделилась и слилась обратно. Наглядный граф также есть
во вкладке Source Control → Graph в VS Code.

---

## Часть 4. Отправка на GitHub под нужным аккаунтом

Имя пользователя пишется **прямо в адресе** (`ИМЯ@github.com`). Тогда Git
Credential Manager войдёт именно под этим аккаунтом, даже если на компьютере
когда-то сохранялся другой.
```bash
git remote add origin https://ИМЯ@github.com/ИМЯ/attendance-tracker.git
git remote -v
git push -u origin --all
```
При первом push откроется окно **Git Credential Manager** → **Sign in with your
browser** → в браузере войдите под нужным аккаунтом → **Authorize
git-ecosystem**. 📸 После этого push завершится. Пароль больше не спросят:
GCM хранит вход в «Диспетчере учётных данных» Windows.

Обновите страницу репозитория на GitHub: должны появиться файлы, коммиты
(**N commits**) и ветки (**2 branches**). 📸

> Если вход всё-таки ушёл не в тот аккаунт: `git credential-manager github list`
> покажет сохранённые аккаунты, а `git credential-manager github logout ИМЯ`
> удалит лишний. После этого повторите `git push`.

---

## Часть 5. Доступ для команды и работа каждого участника

### 5.1 Пригласить участников (владелец репозитория)
Репозиторий → **Settings** → **Collaborators** → **Add people** → ник участника →
**Add**. 📸 Участник принимает приглашение из письма или на
https://github.com/notifications.

### 5.2 Каждый участник у себя
```bash
git clone https://ЕГО_ИМЯ@github.com/ИМЯ/attendance-tracker.git
cd attendance-tracker
git config user.name "Имя Участника"
git config user.email "его_id+ник@users.noreply.github.com"
py -3.13 -m venv venv
venv\Scripts\python.exe -m pip install -r requirements-dev.txt
venv\Scripts\python.exe manage.py migrate
venv\Scripts\python.exe manage.py demo
```
Своя ветка, изменение, отправка:
```bash
git checkout -b feature/ИМЯ-участника
# ...изменить файл, например дописать себя в README в раздел «Команда»...
git commit -am "README: добавлен участник ИМЯ"
git push -u origin feature/ИМЯ-участника
```

### 5.3 Слияние работы участника
Вариант через GitHub (наглядно для скриншотов): на странице репозитория
**Compare & pull request** → **Create pull request** → **Merge pull request**. 📸

Вариант через консоль:
```bash
git checkout main
git pull
git merge feature/ИМЯ-участника
git push
```

Остальные забирают изменения командой `git pull`. Итоговое дерево:
`git log --graph --oneline --all` 📸

---

## Чек-лист по методичке

- [ ] Git установлен
- [ ] Создан репозиторий, добавлены файлы, первый коммит
- [ ] Изменения и новый коммит
- [ ] Новая ветка, изменения в ней, коммит
- [ ] Переключение на основную ветку, изменения, коммит
- [ ] Слияние веток (с разрешением конфликта)
- [ ] Просмотр дерева изменений
- [ ] Создан удалённый репозиторий, проект загружен
- [ ] Доступ всем членам команды
- [ ] Каждый участник склонировал, внёс изменения, слил

Отдельно по методичке ЛР3 нужен документ: технологии и их обоснование,
декомпозиция на модули, список задач с порядком и приоритетом.
