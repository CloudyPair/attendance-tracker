"""Подготовить приватное серверное окружение и каталоги на Debian из-под root."""
from pathlib import Path
import argparse
import os
import re
import secrets

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--domain", default="flag.slowkitchenonline.casa")
args = parser.parse_args()
if not re.fullmatch(r"[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*", args.domain):
    parser.error("Укажите домен без протокола, порта и пути")
if os.name != "posix" or os.geteuid() != 0:
    parser.error("Запустите на сервере Linux из-под root")
root = Path(__file__).resolve().parent.parent
template = (root / "deploy/server.env.example").read_text(encoding="utf-8")
content = template.replace("__DOMAIN__", args.domain).replace("__DJANGO_SECRET__", secrets.token_urlsafe(64))
content = content.replace("__POSTGRES_PASSWORD__", secrets.token_urlsafe(32))
try:
    descriptor = os.open(root / ".env", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    parser.error(".env уже существует. Он сохранен; настройки меняйте вручную")
with os.fdopen(descriptor, "w", encoding="utf-8") as output:
    output.write(content)
for name, mode in (("media", 0o700), ("static", 0o755)):
    directory = root / "deploy/state" / name
    directory.mkdir(parents=True, exist_ok=True)
    os.chown(directory, 10001, 10001)
    directory.chmod(mode)
print("Серверный .env создан с правами 600. Ключи сгенерированы; токен Telegram добавьте вручную.")
