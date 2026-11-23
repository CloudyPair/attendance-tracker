"""Админка - интерфейс технического администратора (ТЗ, раздел 6):
справочники, роли в группе, ручная правка расписания."""
from django.contrib import admin
from django.contrib import messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import path, reverse
from django.utils.html import format_html

from .admin_forms import (ScheduleDownloadForm, StudentManagementForm, StudentManagementFormSet,
                          TeacherManagementForm)
from .errors import DomainError
from .services.administration import AdministrationService
from .services.schedule_import import ScheduleImporter

from .models import (AbsenceReason, AttendanceChange, AttendanceRecord, Course, Delegation,
                     Dispute, Group, Lesson, LinkToken, Notification, Student, Subject,
                     Teacher, TelegramLink, User)


class StudentInline(admin.StackedInline):
    model = Student
    can_delete = False


class TeacherInline(admin.StackedInline):
    model = Teacher
    can_delete = False


class GroupStudentInline(admin.TabularInline):
    model = Student
    form = StudentManagementForm
    formset = StudentManagementFormSet
    fields = ("username", "last_name", "first_name", "role", "password")
    extra = 1


class GroupCourseInline(admin.TabularInline):
    model = Course
    fields = ("subject", "semester", "teachers")
    extra = 1
    verbose_name = "предмет группы"
    verbose_name_plural = "Предметы группы"


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = [StudentInline, TeacherInline]


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    search_fields = ["name"]
    list_display = ("name", "student_count", "schedule_actions")
    inlines = (GroupStudentInline, GroupCourseInline)
    change_form_template = "admin/attendance/group/change_form.html"
    actions = None

    @admin.display(description="Студентов")
    def student_count(self, obj):
        return obj.students.count()

    @admin.display(description="Расписание")
    def schedule_actions(self, obj):
        return format_html('<a href="{}">Загрузить / скачать</a>', reverse("admin:attendance_group_schedule", args=[obj.pk]))

    def get_urls(self):
        return [path("<int:group_id>/schedule/", self.admin_site.admin_view(self.schedule_view),
                     name="attendance_group_schedule")] + super().get_urls()

    def schedule_view(self, request, group_id):
        group = get_object_or_404(Group, pk=group_id)
        if not self.has_change_permission(request, group):
            raise PermissionDenied
        if request.method == "GET" and request.GET.get("download"):
            calendar = settings.MEDIA_ROOT / "schedules" / f"{group.pk}.ics"
            if not calendar.exists() and group.name == "ИВТ-31":
                calendar = settings.BASE_DIR / "data" / "ivt31.ics"
            if not calendar.exists():
                raise Http404("Файл расписания еще не загружен")
            return FileResponse(calendar.open("rb"), as_attachment=True,
                                filename=f"group-{group.pk}.ics", content_type="text/calendar; charset=utf-8")
        form = ScheduleDownloadForm(request.POST if request.method == "POST" else None,
                                    initial={"group_name": group.name})
        if request.method == "POST" and form.is_valid():
            try:
                result = ScheduleImporter().import_miet(group.pk, form.cleaned_data["group_name"])
                self.message_user(request, f"Загружено занятий: {result.created}")
                return HttpResponseRedirect(reverse("admin:attendance_group_change", args=[group.pk]))
            except DomainError as error:
                form.add_error(None, str(error))
        context = {**self.admin_site.each_context(request), "title": f"Расписание {group.name}",
                   "opts": self.model._meta, "group": group, "form": form,
                   "has_schedule": group.courses.filter(lessons__isnull=False).exists()}
        return render(request, "admin/attendance/group/schedule.html", context)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if "_load_schedule" in request.POST:
            try:
                result = ScheduleImporter().import_miet(form.instance.pk)
                self.message_user(request, f"Расписание получено. Занятий: {result.created}")
            except DomainError as error:
                self.message_user(request, f"Группа сохранена. Расписание не загружено: {error}", level=messages.ERROR)

    def response_add(self, request, obj, post_url_continue=None):
        if "_load_schedule" in request.POST:
            return HttpResponseRedirect(reverse("admin:attendance_group_change", args=[obj.pk]))
        return super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        if "_load_schedule" in request.POST:
            return HttpResponseRedirect(reverse("admin:attendance_group_change", args=[obj.pk]))
        return super().response_change(request, obj)

    def get_deleted_objects(self, objs, request):
        return ([f"{obj}: студенты, расписание и отметки группы" for obj in objs],
                {"Группы": len(objs)}, set(), [])

    def delete_model(self, request, obj):
        AdministrationService().delete_group(request.user, obj)


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ["__str__", "group", "role"]
    list_filter = ["group", "role"]
    search_fields = ["user__last_name", "user__first_name", "user__username"]


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    form = TeacherManagementForm
    fields = ("username", "last_name", "first_name", "password", "courses")
    list_display = ("__str__", "assigned_subjects")
    search_fields = ["user__last_name", "user__first_name", "user__username"]
    actions = None

    @admin.display(description="Предметы и группы")
    def assigned_subjects(self, obj):
        return "; ".join(f"{course.subject.name} ({course.group.name})" for course in obj.courses.select_related("subject", "group")) or "—"

    def delete_model(self, request, obj):
        AdministrationService().delete_teacher(request.user, obj)


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    search_fields = ["name"]


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ["subject", "group", "semester", "threshold_percent"]
    list_filter = ["semester", "group"]
    filter_horizontal = ["teachers"]


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ["__str__", "course", "type", "room", "teacher"]
    list_filter = ["type", "course__group", "course__subject"]
    date_hierarchy = "start_at"


class AttendanceChangeInline(admin.TabularInline):
    model = AttendanceChange
    extra = 0
    readonly_fields = ["old_status", "new_status", "changed_by", "changed_at", "reason", "source"]
    can_delete = False


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ["student", "lesson", "status", "marked_by", "last_changed_at"]
    list_filter = ["status", "lesson__course__group"]
    inlines = [AttendanceChangeInline]


@admin.register(Dispute)
class DisputeAdmin(admin.ModelAdmin):
    list_display = ["__str__", "record", "status", "created_at", "resolved_by"]
    list_filter = ["status"]


@admin.register(Delegation)
class DelegationAdmin(admin.ModelAdmin):
    list_display = ["delegate", "granted_by", "granted_at", "valid_until", "revoked_at"]


admin.site.register([AbsenceReason, TelegramLink, LinkToken, Notification])

admin.site.site_header = "ФЛАГ — управление"
admin.site.site_title = "ФЛАГ"
admin.site.index_title = "Управление"
admin.site.index_template = "admin/flag_index.html"
admin.site.enable_nav_sidebar = False
