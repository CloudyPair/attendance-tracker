"""Ошибки предметной области. Сайт и бот переводят их в сообщения пользователю."""


class DomainError(Exception):
    """Базовая ошибка предметной области."""


class AccessDeniedError(DomainError):
    """У пользователя нет права на действие."""


class InvalidChangeError(DomainError):
    """Действие недопустимо в текущем состоянии объекта."""


class ReasonRequiredError(DomainError):
    """Не указана обязательная причина (правка отметки, отказ по спору)."""
