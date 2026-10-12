"""Админка - интерфейс технического администратора (ТЗ, раздел 6):
справочники, роли в группе, ручная правка расписания."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import (AbsenceReason, AttendanceChange, AttendanceRecord, Course, Delegation,
                     Dispute, Group, Lesson, LinkToken, Notification, Student, Subject,
                     Teacher, TelegramLink, User)


class StudentInline(admin.StackedInline):
    model = Student
    can_delete = False


class TeacherInline(admin.StackedInline):
    model = Teacher
    can_delete = False


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = [StudentInline, TeacherInline]


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    search_fields = ["name"]


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ["__str__", "group", "role"]
    list_filter = ["group", "role"]
    search_fields = ["user__last_name", "user__first_name", "user__username"]


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    search_fields = ["user__last_name", "user__first_name", "user__username"]


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
