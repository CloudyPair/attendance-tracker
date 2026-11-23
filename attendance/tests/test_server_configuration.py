from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
import pytest

from attendance_project.database import database_settings


def test_default_local_database_remains_sqlite():
    config = database_settings(Path("project"), {})
    assert config["ENGINE"] == "django.db.backends.sqlite3"
    assert config["NAME"] == Path("project/db.sqlite3")


@pytest.mark.parametrize("backend", ["postgres", "postgresql"])
def test_server_database_uses_explicit_environment(backend):
    config = database_settings(Path("project"), {"DJANGO_DB_BACKEND": backend,
        "POSTGRES_DB": "journal", "POSTGRES_USER": "app", "POSTGRES_PASSWORD": "test-only-password",
        "POSTGRES_HOST": "database", "POSTGRES_PORT": "5433"})
    assert config["ENGINE"] == "django.db.backends.postgresql"
    assert (config["NAME"], config["USER"], config["HOST"], config["PORT"]) == ("journal", "app", "database", "5433")
    assert config["CONN_HEALTH_CHECKS"] is True


@pytest.mark.parametrize("environment", [{"DJANGO_DB_BACKEND": "unknown"}, {"DJANGO_DB_BACKEND": "postgres"}])
def test_invalid_backend_or_missing_password_fails_early(environment):
    with pytest.raises(ImproperlyConfigured):
        database_settings(Path("project"), environment)


def test_https_proxy_header_prevents_redirect_loop_and_sets_secure_csrf(client, settings):
    settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    settings.SECURE_SSL_REDIRECT = True
    settings.CSRF_COOKIE_SECURE = True
    settings.ALLOWED_HOSTS = ["flag.slowkitchenonline.casa"]
    direct = client.get("/login/", HTTP_HOST="flag.slowkitchenonline.casa")
    assert direct.status_code == 301
    assert direct.url == "https://flag.slowkitchenonline.casa/login/"
    proxied = client.get("/login/", HTTP_HOST="flag.slowkitchenonline.casa", HTTP_X_FORWARDED_PROTO="https")
    assert proxied.status_code == 200
    assert proxied.cookies["csrftoken"]["secure"] is True
