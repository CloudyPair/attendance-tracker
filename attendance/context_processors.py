"""Данные для шапки сайта на каждой странице: «Вошёл как Иванова М.В., Староста»."""


def short_name(user) -> str:
    """Фамилия и инициал имени: «Иванова М.». Без фамилии - логин."""
    if not user.last_name:
        return user.username
    initial = f" {user.first_name[0]}." if user.first_name else ""
    return f"{user.last_name}{initial}"


def role_name(user) -> str:
    student = getattr(user, "student", None)
    if student is not None:
        return student.get_role_display()
    if hasattr(user, "teacher"):
        return "Преподаватель"
    if user.is_staff:
        return "Администратор"
    return ""


def navigation(request):
    if not request.user.is_authenticated:
        return {}
    return {
        "nav_name": short_name(request.user),
        "nav_role": role_name(request.user),
    }
