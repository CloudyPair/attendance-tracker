# Установка на Debian 12

Схема: Nginx сервера → 127.0.0.1:18080 → Gunicorn/Python 3.13 в Docker.
PostgreSQL 17 и бот запускаются отдельными контейнерами проекта `flag`.
База не публикует порт наружу. Nginx раздает только статику; документы
скачиваются через Django после проверки прав.

Команды выполняются по SSH от root. Предполагается путь `/opt/flag` и домен
`flag.slowkitchenonline.casa`. Настройки других сайтов и контейнеров сохраняются.

## 1 Подготовка сервера

Проверить слушающие порты:

```bash
ss -ltnp '( sport = :80 or sport = :443 or sport = :18080 )'
```

На текущем VPS порт 80 занимает Nginx, 443 — Xray, 18080 свободен.
Для HTTPS сайта порт 443 нужно освободить. Если Xray пока не используется:

```bash
systemctl disable --now xray
```

Это останавливает только службу Xray. Существующий сторонний Telegram-бот
останавливать не требуется. Для возвращения Xray позднее понадобится
развести его порт с HTTPS сайта и включить службу снова.

Установить необходимые пакеты и Docker из официального репозитория:

```bash
apt install -y ca-certificates curl git nginx certbot python3-certbot-nginx
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/debian
Suites: bookworm
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
docker compose version
```

Если Docker уже установлен и используется другими сервисами, используйте
существующую установку с Compose plugin. Переустанавливать ее не требуется.

В сетевом экране VPS должны быть разрешены входящие TCP 80 и 443. Порт 18080
открывать наружу не требуется: он привязан только к loopback.

## 2 Клонирование и настройки

Сначала отправьте серверные файлы в GitHub. Затем на VPS:

```bash
git clone https://github.com/CloudyPair/attendance-tracker.git /opt/flag
cd /opt/flag
python3 deploy/configure.py
```

Если репозиторий уже склонирован в этот каталог, используйте `git pull --ff-only`.
`configure.py` создает `.env` с новыми случайными ключами и правами 600,
а также каталоги статики и документов с владельцем UID 10001 для контейнеров.
Существующий `.env` скрипт не перезаписывает.

Токен бота в Git отсутствует. Добавьте его на сервере вручную:

```bash
nano .env
```

Заполните `TELEGRAM_BOT_TOKEN`. Имя бота уже задано: `flagtag34bot`.
Не копируйте локальный ключ Django на сервер: здесь уже создан отдельный.

## 3 База и приложение

```bash
cd /opt/flag
docker compose config --quiet
docker compose build
docker compose up -d --wait db
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py collectstatic --noinput
docker compose run --rm web python manage.py seed_demo
docker compose run --rm web python manage.py fill_demo_attendance --through 2026-11-23
docker compose run --rm web python manage.py createsuperuser
docker compose up -d --wait web
docker compose ps
```

`createsuperuser` интерактивно создаст нового администратора сервера.
`seed_demo` создаст учебные аккаунты с паролем 1234 и реальное расписание.
Это новая серверная БД: прежние споры, привязки и ручные изменения с компьютера
не копируются этими командами. Если нужны текущие локальные данные,
переносите их отдельным согласованным экспортом перед заполнением сервера.

Проверить приложение через внутренний порт:

```bash
curl -I -H 'Host: flag.slowkitchenonline.casa' -H 'X-Forwarded-Proto: https' http://127.0.0.1:18080/login/
docker compose logs --tail=60 web
```

Ожидается HTTP 200. Внутренний запрос явно указывает HTTPS-протокол прокси,
чтобы не получить редирект приложения на еще не подключенный внешний HTTPS.

## 4 Nginx и HTTPS

Добавить отдельный сайт, сохранив существующие конфигурации:

```bash
install -m 0644 deploy/nginx.conf /etc/nginx/sites-available/flag
ln -s /etc/nginx/sites-available/flag /etc/nginx/sites-enabled/flag
nginx -t
systemctl reload nginx
certbot --nginx -d flag.slowkitchenonline.casa --redirect
certbot renew --dry-run
```

Если ссылка `sites-enabled/flag` уже существует, повторно создавать ее не нужно.
Certbot спросит адрес электронной почты и согласие с условиями. DNS домена
должен указывать на этот VPS; TCP 80/443 должны быть доступны извне.

Проверить: <https://flag.slowkitchenonline.casa/login/> и
<https://flag.slowkitchenonline.casa/admin/>.

После получения сертификата не копируйте исходный `deploy/nginx.conf`
поверх рабочего файла повторно: Certbot добавляет туда настройки HTTPS.

## 5 Бот

Один токен должен обслуживаться одним процессом polling. Перед серверным
запуском остановите прежний локальный процесс именно бота ФЛАГ. Другие
боты с другими токенами могут работать независимо.

```bash
cd /opt/flag
docker compose --profile telegram up -d bot
docker compose logs --tail=60 bot
```

После создания новой серверной БД привяжите Telegram заново через серверный
личный кабинет. Серверные уведомления складываются в очередь без ожидания
сети в HTTP-запросе; отправкой и повторными попытками занимается процесс бота.
Контейнеры запускаются автоматически после перезагрузки Docker.

## Обновление и резервная копия

```bash
cd /opt/flag
bash deploy/backup.sh
git pull --ff-only
docker compose build
docker compose stop web bot
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py collectstatic --noinput
docker compose up -d --wait web
docker compose --profile telegram up -d bot
```

Последнюю команду выполняйте, если бот уже настроен. `backup.sh` сохраняет
дамп PostgreSQL, документы и `.env` в приватный каталог `backups/` с правами
только для владельца. Резервную копию следует переносить и за пределы VPS.
Рабочие данные сохраняются в томе PostgreSQL и `deploy/state/media`.

Диагностика: `docker compose ps`, `docker compose logs --tail=100 web`,
`docker compose logs --tail=100 bot`, `journalctl -u nginx --since '10 minutes ago'`.

GitHub Actions проверяет SQLite и PostgreSQL, а также сборку Docker-образа.
Локально на Windows без Docker проверяется SQLite и код конфигурации;
контейнерный запуск нужно подтвердить успешным CI или на VPS.
