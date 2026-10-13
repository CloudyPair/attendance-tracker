"""Страницы сайта (WebViews на UML/class_services.puml).

Итерация 1: вход, выход и главная страница. Вход и выход - стандартные
LoginView/LogoutView Django со своим шаблоном (см. attendance/urls.py).
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def home(request):
    return render(request, "attendance/home.html")
