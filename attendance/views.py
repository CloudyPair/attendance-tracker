from datetime import datetime, time, timedelta
import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from attendance.errors import AccessDeniedError, ConcurrentChangeError, DomainError
from attendance.calendarutils import academic_week_type
from attendance.forms import MarkFormSet, MarkingForm, PeriodForm, ScheduleFilterForm, ThresholdForm
from attendance.models import Lesson
from attendance.services import build_services
from attendance.services.exporters import EXPORTERS


SHEET_SALT = "attendance.marking-sheet.v1"


def _student(user):
    student = getattr(user, "student", None)
    if student is None:
        raise PermissionDenied("Для этой страницы нужен профиль студента")
    return student


def _midnight(day):
    return timezone.make_aware(datetime.combine(day, time.min), timezone.get_default_timezone())


@login_required
@require_GET
def lessons_page(request):
    if request.user.is_staff:
        return redirect("admin:index")
    if getattr(request.user, "student", None) is None:
        if getattr(request.user, "teacher", None):
            return redirect("attendance:teacher")
        if request.user.is_staff:
            return redirect("admin:index")
        return render(request, "attendance/no_profile.html", status=403)
    student = _student(request.user)
    today = timezone.localdate()
    form = ScheduleFilterForm(request.GET or {"date": today.isoformat(), "mode": "day"})
    if not form.is_valid():
        return render(request, "attendance/lessons.html", {"filter_form": form, "lessons": [],
                      "active_nav": "lessons", "today": today}, status=400)
    selected = form.cleaned_data["date"]
    mode = form.cleaned_data["mode"] or "day"
    start = selected - timedelta(days=selected.weekday()) if mode == "week" else selected
    end = start + timedelta(days=7 if mode == "week" else 1)
    service = build_services().attendance
    rows = service.lessons_for_student(student, _midnight(start), _midnight(end))
    manager = service.is_responsible(student)
    today_rows = (rows if start == today and end == today + timedelta(days=1)
                  else service.lessons_for_student(student, _midnight(today), _midnight(today + timedelta(days=1))))
    completed = sum(row.marked_students == row.total_students if manager
                    else row.status != "NOT_MARKED" for row in today_rows)
    by_day = {}
    for row in rows:
        by_day.setdefault(timezone.localtime(row.lesson.start_at).date(), []).append(row)
    days = [{"date": start + timedelta(days=offset),
             "lessons": by_day.get(start + timedelta(days=offset), [])}
            for offset in range(7 if mode == "week" else 1)]
    return render(request, "attendance/lessons.html", {
        "active_nav": "lessons", "filter_form": form, "lessons": rows, "selected_date": selected,
        "today": today, "mode": mode, "is_manager": manager, "today_completed": completed,
        "today_total": len(today_rows), "days": days,
        "week_type": academic_week_type(selected, student.group.name, student.group_id),
        "period_start": start, "period_end": end - timedelta(days=1),
        "previous_date": selected - timedelta(days=7 if mode == "week" else 1),
        "next_date": selected + timedelta(days=7 if mode == "week" else 1)})


@login_required
@require_http_methods(["GET", "POST"])
def marking_page(request, lesson_id):
    student = _student(request.user)
    service = build_services().attendance
    try:
        lesson = service.lesson_for_marking(student, lesson_id)
        records = service.open_lesson(student, lesson_id)
    except Lesson.DoesNotExist as error:
        raise Http404("Занятие не найдено") from error
    except AccessDeniedError as error:
        raise PermissionDenied(str(error)) from error
    initial = [{"student_id": record.student_id, "status": record.status} for record in records]
    token = signing.dumps({"lesson": lesson.pk, "actor": student.pk, "version": lesson.marking_version,
                           "students": [record.student_id for record in records]}, salt=SHEET_SALT)
    form = MarkingForm(request.POST or None, initial={"sheet": token})
    formset = MarkFormSet(request.POST or None, initial=initial, prefix="marks")
    error_message = ""
    status = 200
    if request.method == "POST":
        if form.is_valid() and formset.is_valid():
            try:
                sheet = signing.loads(form.cleaned_data["sheet"], salt=SHEET_SALT, max_age=86400)
                ids = [item.cleaned_data["student_id"] for item in formset]
                if (sheet["lesson"] != lesson.pk or sheet["actor"] != student.pk
                        or ids != sheet["students"] or ids != [record.student_id for record in records]):
                    raise signing.BadSignature("Состав группы изменился или форма повреждена")
                service.save_marks(student, lesson.pk,
                                   {item.cleaned_data["student_id"]: item.cleaned_data["status"] for item in formset},
                                   form.cleaned_data["reason"], expected_version=sheet["version"],
                                   reasons={item.cleaned_data["student_id"]: item.cleaned_data["change_reason"]
                                            for item in formset if item.cleaned_data["change_reason"]})
                messages.success(request, "Отметки сохранены. Изменения записаны в историю.")
                return redirect("attendance:marking", lesson_id=lesson.pk)
            except ConcurrentChangeError as error:
                error_message, status = str(error), 409
            except (signing.BadSignature, KeyError, TypeError):
                error_message, status = "Форма устарела или повреждена. Откройте занятие заново.", 400
            except DomainError as error:
                error_message, status = str(error), 400
        else:
            error_message, status = "Проверьте отметки и поля формы. Изменения не сохранены.", 400
    return render(request, "attendance/marking.html", {
        "active_nav": "lessons", "lesson": lesson, "form": form, "formset": formset,
        "record_forms": list(zip(records, formset)), "error_message": error_message,
        "conflict": status == 409, "total_students": len(records)}, status=status)


@login_required
@require_GET
def my_attendance_page(request):
    student = _student(request.user)
    services = build_services()
    from_, to = services.statistics.period_for_student(student)
    initial = {"start": timezone.localtime(from_).date().isoformat(),
               "end": (timezone.localtime(to).date() - timedelta(days=1)).isoformat()}
    period_data = request.GET.copy()
    for name, value in initial.items():
        if name not in period_data:
            period_data[name] = value
    form = PeriodForm(period_data)
    reports, rows = [], []
    if form.is_valid():
        start = _midnight(form.cleaned_data["start"])
        end = _midnight(form.cleaned_data["end"] + timedelta(days=1))
        reports = services.statistics.for_student(student, start, end)
        rows = services.attendance.lessons_for_student(student, start, end)
    page = Paginator(rows, 15).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    if form.is_valid():
        params["start"] = form.cleaned_data["start"].isoformat()
        params["end"] = form.cleaned_data["end"].isoformat()
    return render(request, "attendance/my_attendance.html", {
        "active_nav": "statistics", "period_form": form, "reports": reports, "page_obj": page,
        "query_string": params.urlencode(), "marked": sum(item.total.marked for item in reports),
        "missed": sum(item.total.missed for item in reports),
        "unmarked": sum(item.total.not_marked for item in reports)}, status=200 if form.is_valid() else 400)


@login_required
@require_http_methods(["GET", "POST"])
def teacher_stats_page(request):
    teacher = getattr(request.user, "teacher", None)
    if teacher is None:
        raise PermissionDenied("Для этой страницы нужен профиль преподавателя")
    services = build_services()
    courses = services.courses.for_teacher(teacher)
    legacy_course = next((course for course in courses if str(course.pk) == request.GET.get("course")), None)
    if request.GET.get("course") and legacy_course is None:
        raise Http404("Курс не найден")

    # В обозначениях МИЭТ ИВТ-31 — третий курс, ИВТ-24М — второй.
    # Неопознанные названия не получают вымышленный курс обучения.
    def study_year(course):
        match = re.search(r"-([1-6])\d", course.group.name)
        return match[1] if match else "unspecified"

    years = sorted({study_year(course) for course in courses})
    year_options = [{"value": value, "label": f"{value} курс" if value != "unspecified" else "Курс не указан"}
                    for value in years]
    default = legacy_course or (courses[0] if courses else None)
    has_filters = any(name in request.GET for name in ("year", "subject", "group"))
    selected_year = (request.GET.get("year", "") if has_filters
                     else study_year(default) if default else "")
    if selected_year not in years:
        selected_year = ""
    year_courses = [course for course in courses if study_year(course) == selected_year]
    subjects = sorted({course.subject_id: course.subject for course in year_courses}.values(),
                      key=lambda subject: subject.name.casefold())
    selected_subject = (request.GET.get("subject", "") if has_filters
                        else str(default.subject_id) if default else "")
    if selected_subject not in {str(subject.pk) for subject in subjects}:
        selected_subject = ""
    subject_courses = [course for course in year_courses if str(course.subject_id) == selected_subject]
    groups = sorted({course.group_id: course.group for course in subject_courses}.values(),
                    key=lambda group: group.name.casefold())
    selected_group = (request.GET.get("group", "") if has_filters
                      else str(default.group_id) if default else "")
    if selected_group not in {str(group.pk) for group in groups}:
        selected_group = ""
    selected = next((course for course in subject_courses if str(course.group_id) == selected_group), None)
    report = None
    period_form = None
    threshold_form = None
    query = request.GET.copy()
    query.pop("format", None)
    if selected:
        from_, to = services.statistics.period_for_course(teacher, selected)
        period_data = {"start": request.GET.get("start", timezone.localtime(from_).date().isoformat()),
                       "end": request.GET.get("end", (timezone.localtime(to).date() - timedelta(days=1)).isoformat())}
        period_form = PeriodForm(period_data)
        threshold_form = ThresholdForm(request.POST if request.method == "POST" else None,
                                        initial={"threshold": selected.threshold_percent})
        if request.method == "POST" and threshold_form.is_valid():
            services.courses.set_threshold(teacher, selected.pk, threshold_form.cleaned_data["threshold"])
            messages.success(request, "Порог посещаемости изменен")
            return redirect(f"{request.path}?{query.urlencode()}")
        if period_form.is_valid():
            from_ = _midnight(period_form.cleaned_data["start"])
            to = _midnight(period_form.cleaned_data["end"] + timedelta(days=1))
            report = services.statistics.for_course(teacher, selected, from_, to)
            for key, value in {"year": selected_year, "subject": selected_subject, "group": selected_group,
                               "start": period_form.cleaned_data["start"].isoformat(),
                               "end": period_form.cleaned_data["end"].isoformat()}.items():
                query[key] = value
            if request.method == "GET" and request.GET.get("format"):
                format_ = request.GET["format"]
                if format_ not in ("csv", "xlsx"):
                    raise Http404("Формат не поддерживается")
                content_type = ("text/csv; charset=utf-8" if format_ == "csv"
                                else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                response = HttpResponse(EXPORTERS[format_].export(report), content_type=content_type)
                response["Content-Disposition"] = f'attachment; filename="attendance-{selected.pk}.{format_}"'
                return response
    return render(request, "attendance/teacher.html", {
        "active_nav": "teacher", "courses": courses, "selected_course": selected, "report": report,
        "year_options": year_options, "subjects": subjects, "groups": groups,
        "selected_year": selected_year, "selected_subject": selected_subject, "selected_group": selected_group,
        "period_form": period_form, "threshold_form": threshold_form, "report_query": query.urlencode()})


@login_required
@require_GET
def teacher_history_page(request, course_id, student_id):
    teacher = getattr(request.user, "teacher", None)
    if teacher is None:
        raise PermissionDenied
    services = build_services()
    course = next((item for item in services.courses.for_teacher(teacher) if item.pk == course_id), None)
    if course is None:
        raise Http404("Предмет не найден")
    from_, to = services.statistics.period_for_course(teacher, course)
    period = PeriodForm({"start": request.GET.get("start", timezone.localtime(from_).date().isoformat()),
                         "end": request.GET.get("end", (timezone.localtime(to).date() - timedelta(days=1)).isoformat())})
    if not period.is_valid():
        raise Http404("Некорректный период")
    try:
        entries = services.statistics.get_student_history(teacher, course, student_id,
            _midnight(period.cleaned_data["start"]), _midnight(period.cleaned_data["end"] + timedelta(days=1)))
    except AccessDeniedError as error:
        raise PermissionDenied(str(error)) from error
    back = request.GET.copy()
    back["course"] = str(course.pk)
    return render(request, "attendance/teacher_history.html", {
        "active_nav": "teacher", "course": course, "page_obj": Paginator(entries, 30).get_page(request.GET.get("page")),
        "back_query": back.urlencode(), "period": period,
        "history_query": f"start={period.cleaned_data['start'].isoformat()}&end={period.cleaned_data['end'].isoformat()}"})
