"""Страницы причин, споров, замены и привязки Telegram."""
from urllib.parse import urlencode

from django.conf import settings
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from attendance.errors import AccessDeniedError, DomainError
from attendance.models import AbsenceReason, Dispute
from attendance.services import build_services
from attendance.views import _student


class DisputeForm(forms.Form):
    comment = forms.CharField(label="Объяснение для преподавателя", max_length=2000,
        widget=forms.Textarea(attrs={"rows": 3}))
    attachment = forms.FileField(label="Справка или другой документ до 5 МБ", required=False)


@login_required
@require_GET
def absences_page(request):
    student = _student(request.user)
    rows = build_services().disputes.absences(student)
    return render(request, "attendance/absences.html", {"active_nav": "absences",
        "page_obj": Paginator(rows, 15).get_page(request.GET.get("page"))})


@login_required
@require_http_methods(["GET", "POST"])
def absence_page(request, record_id):
    student = _student(request.user)
    service = build_services().disputes
    try:
        record = service.own_record(student, record_id)
    except AccessDeniedError as error:
        raise PermissionDenied(str(error)) from error
    except DomainError as error:
        messages.error(request, str(error))
        return redirect("attendance:absences")
    previous = getattr(record, "absence_reason", None)
    dispute_form = DisputeForm(initial={"comment": previous.text if previous else ""}, prefix="dispute")
    if request.method == "POST":
        dispute_form = DisputeForm(request.POST, request.FILES, prefix="dispute")
        if dispute_form.is_valid():
            try:
                service.create(student, record_id, **dispute_form.cleaned_data)
                messages.success(request, "Заявка отправлена преподавателю предмета")
                return redirect("attendance:disputes")
            except DomainError as error:
                dispute_form.add_error(None, str(error))
    disputes = record.disputes.order_by("-created_at")
    return render(request, "attendance/absence.html", {"active_nav": "absences", "record": record,
        "dispute_form": dispute_form, "disputes": disputes,
        "has_open_dispute": disputes.filter(status="OPEN").exists()})


@login_required
@require_http_methods(["GET", "POST"])
def disputes_page(request):
    teacher = getattr(request.user, "teacher", None)
    actor = teacher or _student(request.user)
    service = build_services().disputes
    if request.method == "POST":
        if teacher is None:
            raise PermissionDenied("Решение принимает преподаватель предмета")
        try:
            dispute_id = int(request.POST.get("dispute_id", "0"))
            action = request.POST.get("action")
            if action == "delete":
                service.delete(teacher, dispute_id)
                messages.success(request, "Спор удален из истории")
            elif action in ("fix", "reject"):
                service.resolve(teacher, dispute_id, action == "fix", request.POST.get("comment", ""))
                messages.success(request, "Решение сохранено")
            else:
                raise DomainError("Неизвестное действие")
            return redirect(f"{request.path}?{urlencode({'page': request.GET.get('page', '1')})}")
        except (DomainError, ValueError) as error:
            messages.error(request, str(error))
    rows = [{"dispute": d, "can_resolve": service.can_resolve(actor, d),
             "can_delete": service.can_delete(actor, d)} for d in service.list_for(actor)]
    return render(request, "attendance/disputes.html", {"active_nav": "disputes",
        "is_teacher": teacher is not None, "page_obj": Paginator(rows, 15).get_page(request.GET.get("page"))})


@login_required
@require_http_methods(["GET", "POST"])
def delegation_page(request):
    student = _student(request.user)
    service = build_services().delegation
    if request.method == "POST":
        try:
            action = request.POST.get("action")
            if action == "assign":
                service.assign_by_id(student, int(request.POST.get("delegate_id", "0")))
                messages.success(request, "Замена назначена до 00:00")
            elif action == "revoke":
                service.revoke(student, int(request.POST.get("delegation_id", "0")))
                messages.success(request, "Замена отозвана")
            else:
                raise DomainError("Неизвестное действие")
            return redirect("attendance:delegation")
        except (DomainError, ValueError) as error:
            messages.error(request, str(error))
    return render(request, "attendance/delegation.html", {"active_nav": "delegation",
        "can_assign": student.is_headman_or_deputy(), "candidates": service.candidates(student),
        "delegations": service.active_for(student)})


@login_required
@require_http_methods(["GET", "POST"])
def telegram_link_page(request):
    student = _student(request.user)
    service = build_services().telegram_link
    deep_link = ""
    configured = bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_BOT_USERNAME)
    if request.method == "POST":
        try:
            action = request.POST.get("action")
            if action == "link" and configured:
                token = service.create_link_token(student)
                deep_link = f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?{urlencode({'start': token})}"
            elif action == "unlink":
                service.unlink(student)
                messages.success(request, "Telegram отвязан")
            elif action in ("enable", "disable"):
                service.set_notifications(student, action == "enable")
                messages.success(request, "Настройки уведомлений сохранены")
            else:
                raise DomainError("Бот пока не настроен")
        except DomainError as error:
            messages.error(request, str(error))
        if not deep_link:
            return redirect("attendance:telegram")
    response = render(request, "attendance/telegram.html", {"active_nav": "telegram", "configured": configured,
        "link": service.get_link(student), "deep_link": deep_link, "bot_username": settings.TELEGRAM_BOT_USERNAME})
    response["Cache-Control"] = "no-store"
    # Формам нужен Origin/Referer своего сайта; внешние ссылки уже имеют rel=noreferrer.
    response["Referrer-Policy"] = "same-origin"
    return response


@login_required
@require_GET
def absence_attachment(request, reason_id):
    try:
        attachment = build_services().disputes.attachment_for(request.user, reason_id)
        response = FileResponse(attachment.open("rb"), as_attachment=True,
            filename=attachment.name.rsplit("/", 1)[-1], content_type="application/octet-stream")
        response["Cache-Control"] = "private, no-store"
        return response
    except AccessDeniedError as error:
        raise PermissionDenied(str(error)) from error
    except (AbsenceReason.DoesNotExist, DomainError, FileNotFoundError) as error:
        raise Http404("Вложение не найдено") from error


@login_required
@require_GET
def dispute_attachment(request, dispute_id):
    try:
        attachment = build_services().disputes.attachment_for_dispute(request.user, dispute_id)
        response = FileResponse(attachment.open("rb"), as_attachment=True,
            filename=attachment.name.rsplit("/", 1)[-1], content_type="application/octet-stream")
        response["Cache-Control"] = "private, no-store"
        return response
    except AccessDeniedError as error:
        raise PermissionDenied(str(error)) from error
    except (Dispute.DoesNotExist, DomainError, FileNotFoundError) as error:
        raise Http404("Вложение не найдено") from error
