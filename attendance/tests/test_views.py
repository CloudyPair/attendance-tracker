import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from attendance.models import AttendanceChange, AttendanceRecord, AttendanceStatus as S


pytestmark = pytest.mark.django_db


def payload(response, value=S.PRESENT):
    forms = response.context["formset"]
    data = {"sheet": response.context["form"]["sheet"].value(), "reason": "",
            "marks-TOTAL_FORMS": len(forms), "marks-INITIAL_FORMS": len(forms),
            "marks-MIN_NUM_FORMS": 0, "marks-MAX_NUM_FORMS": 500}
    for index, form in enumerate(forms):
        data[f"marks-{index}-student_id"] = form["student_id"].value()
        data[f"marks-{index}-status"] = value
    return data


def test_anonymous_user_is_sent_to_login(client):
    response = client.get(reverse("attendance:lessons"))
    assert response.status_code == 302
    assert "/login/?next=" in response.url
    assert client.get(reverse("attendance:login")).status_code == 200


def test_login_logout_and_csrf_protection(sample):
    client = Client(enforce_csrf_checks=True)
    response = client.get(reverse("attendance:login"))
    credentials = {"username": "headman", "password": "test-password"}
    assert client.post(reverse("attendance:login"), credentials).status_code == 403
    credentials["csrfmiddlewaretoken"] = response.cookies["csrftoken"].value
    assert client.post(reverse("attendance:login"), credentials).status_code == 302
    assert client.get(reverse("attendance:logout")).status_code == 405
    assert client.post(reverse("attendance:logout"), {"csrfmiddlewaretoken": client.cookies["csrftoken"].value}).status_code == 302


def test_member_can_read_schedule_and_own_attendance(client, sample):
    client.force_login(sample.member.user)
    response = client.get(reverse("attendance:lessons"))
    assert response.status_code == 200
    assert sample.course.subject.name in response.content.decode()
    assert "Отметить группу" not in response.content.decode()
    response = client.get(reverse("attendance:statistics"))
    assert response.status_code == 200
    assert response.context["reports"][0].total.not_marked == 1
    assert client.get(reverse("attendance:marking", args=[sample.lesson.pk])).status_code == 403
    assert client.get(reverse("attendance:teacher")).status_code == 403


def test_teacher_landing_and_access(client, sample):
    client.force_login(sample.teacher.user)
    assert client.get(reverse("attendance:lessons")).url == reverse("attendance:teacher")
    response = client.get(reverse("attendance:teacher"))
    assert response.status_code == 200
    assert response.context["selected_course"] == sample.course
    assert client.get(reverse("attendance:teacher") + "?course=999999").status_code == 404


def test_headman_can_save_full_roster_then_stale_tab_is_rejected(client, sample):
    client.force_login(sample.headman.user)
    url = reverse("attendance:marking", args=[sample.lesson.pk])
    first_tab = client.get(url)
    data = payload(first_tab)
    assert client.post(url, data).status_code == 302
    assert AttendanceRecord.objects.filter(status=S.PRESENT).count() == 3
    assert AttendanceChange.objects.count() == 3
    data["marks-0-status"] = S.ABSENT
    data["reason"] = "Осталась старая вкладка"
    response = client.post(url, data)
    assert response.status_code == 409
    assert AttendanceRecord.objects.filter(status=S.PRESENT).count() == 3


def test_web_edit_without_reason_does_not_save(client, sample):
    client.force_login(sample.headman.user)
    url = reverse("attendance:marking", args=[sample.lesson.pk])
    assert client.post(url, payload(client.get(url))).status_code == 302
    data = payload(client.get(url), S.ABSENT)
    response = client.post(url, data)
    assert response.status_code == 400
    assert AttendanceRecord.objects.filter(status=S.PRESENT).count() == 3
    data["reason"] = "Ошибочная первая отметка"
    assert client.post(url, data).status_code == 302
    assert AttendanceRecord.objects.filter(status=S.ABSENT).count() == 3


def test_signed_roster_rejects_injected_student(client, sample):
    client.force_login(sample.headman.user)
    url = reverse("attendance:marking", args=[sample.lesson.pk])
    data = payload(client.get(url))
    data["marks-0-student_id"] = sample.outsider.pk
    assert client.post(url, data).status_code == 400
    assert not AttendanceChange.objects.exists()


def test_signed_sheet_is_bound_to_actor(client, sample):
    client.force_login(sample.headman.user)
    url = reverse("attendance:marking", args=[sample.lesson.pk])
    data = payload(client.get(url))
    client.force_login(sample.deputy.user)
    assert client.post(url, data).status_code == 400


def test_invalid_and_missing_lesson(client, sample):
    client.force_login(sample.headman.user)
    assert client.get(reverse("attendance:marking", args=[999999])).status_code == 404
    assert client.get(reverse("attendance:lessons") + "?date=garbage").status_code == 400
    assert client.get(reverse("attendance:statistics") + "?start=2026-12-01&end=2026-11-01").status_code == 400


def test_foreign_group_cannot_view_marking(client, sample):
    client.force_login(sample.outsider.user)
    assert client.get(reverse("attendance:marking", args=[sample.lesson.pk])).status_code == 403


def test_account_without_profile_has_clear_empty_state(client):
    user = get_user_model().objects.create_user("unassigned")
    client.force_login(user)
    response = client.get(reverse("attendance:lessons"))
    assert response.status_code == 403
    assert "Нужен учебный профиль" in response.content.decode()


@pytest.mark.parametrize("date_value", ["0001-01-01", "9999-12-31"])
def test_extreme_dates_are_validation_errors_not_server_errors(client, sample, date_value):
    client.force_login(sample.member.user)
    assert client.get(reverse("attendance:lessons"), {"date": date_value}).status_code == 400
    assert client.get(reverse("attendance:statistics"), {"start": date_value, "end": date_value}).status_code == 400
