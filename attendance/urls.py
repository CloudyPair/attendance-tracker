from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from . import student_views

app_name = "attendance"

urlpatterns = [
    path("absences/", student_views.absences_page, name="absences"),
    path("absences/<int:record_id>/", student_views.absence_page, name="absence"),
    path("attachments/<int:reason_id>/", student_views.absence_attachment, name="absence_attachment"),
    path("disputes/", student_views.disputes_page, name="disputes"),
    path("disputes/<int:dispute_id>/attachment/", student_views.dispute_attachment, name="dispute_attachment"),
    path("delegation/", student_views.delegation_page, name="delegation"),
    path("telegram/", student_views.telegram_link_page, name="telegram"),
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html",
                                              redirect_authenticated_user=True), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", views.lessons_page, name="lessons"),
    path("lessons/<int:lesson_id>/mark/", views.marking_page, name="marking"),
    path("my-attendance/", views.my_attendance_page, name="statistics"),
    path("teacher/", views.teacher_stats_page, name="teacher"),
    path("teacher/<int:course_id>/students/<int:student_id>/history/", views.teacher_history_page, name="teacher_history"),
]
