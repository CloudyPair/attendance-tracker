"""Выбор локальной SQLite или серверной PostgreSQL через окружение."""
from django.core.exceptions import ImproperlyConfigured


def database_settings(base_dir, environment):
    backend = environment.get("DJANGO_DB_BACKEND", "sqlite").strip().lower()
    if backend == "sqlite":
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": base_dir / "db.sqlite3",
                "OPTIONS": {"timeout": 20}}
    if backend not in ("postgres", "postgresql"):
        raise ImproperlyConfigured("DJANGO_DB_BACKEND должен быть sqlite или postgres")
    password = environment.get("POSTGRES_PASSWORD", "")
    if not password:
        raise ImproperlyConfigured("Для PostgreSQL задайте POSTGRES_PASSWORD")
    return {"ENGINE": "django.db.backends.postgresql", "NAME": environment.get("POSTGRES_DB", "flag"),
            "USER": environment.get("POSTGRES_USER", "flag"), "PASSWORD": password,
            "HOST": environment.get("POSTGRES_HOST", "db"), "PORT": environment.get("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": 60, "CONN_HEALTH_CHECKS": True}
