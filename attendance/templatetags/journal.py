from django import template

register = template.Library()


@register.filter(is_safe=True)
def ui_text(value):
    """Единое написание отображаемого текста без изменения исходных данных."""
    if value is None:
        return ""
    return str(value).translate(str.maketrans("\u0451\u0401", "\u0435\u0415", "\u00b7"))
