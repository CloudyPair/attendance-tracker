"""Приемка HTTP-сценариев с реальной проверкой доступа и CSRF."""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from attendance.models import AttendanceRecord, AttendanceStatus as S, Dispute, DisputeStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def absent(sample):
    record = AttendanceRecord.objects.create(lesson=sample.lesson, student=sample.member)
    record.change(S.ABSENT, sample.headman, "", sample.now)
    return record


def test_web_student_submits_document_teacher_reads_accepts_and_deletes(client, sample, absent):
    client.force_login(sample.member.user)
    response = client.post(reverse("attendance:absence", args=[absent.pk]), {
        "dispute-comment": "Справка подтверждает посещение",
        "dispute-attachment": SimpleUploadedFile("proof.pdf", b"%PDF-proof")})
    assert response.status_code == 302
    dispute = Dispute.objects.get()
    download = reverse("attendance:dispute_attachment", args=[dispute.pk])
    response = client.get(download)
    assert b"".join(response.streaming_content) == b"%PDF-proof"
    assert "attachment;" in response["Content-Disposition"]
    response.close()
    client.force_login(sample.teacher.user)
    page = reverse("attendance:disputes")
    response = client.get(page)
    assert response.context["page_obj"].object_list[0]["can_resolve"]
    assert download in response.content.decode()
    assert client.post(page, {"dispute_id": dispute.pk, "action": "fix"}).status_code == 302
    absent.refresh_from_db()
    assert absent.status == S.PRESENT
    assert client.post(page, {"dispute_id": dispute.pk, "action": "delete"}).status_code == 302
    assert not Dispute.objects.filter(pk=dispute.pk).exists()
    assert absent.changes.count() == 2
    assert client.get(download).status_code == 404


@pytest.mark.parametrize("actor", ["headman", "deputy", "outsider", "foreign_teacher"])
def test_documents_and_decisions_are_private(client, sample, absent, actor):
    dispute = sample.services.disputes.create(sample.member, absent.pk, "Документ",
        SimpleUploadedFile("proof.pdf", b"private"))
    client.force_login(getattr(sample, actor).user)
    assert client.get(reverse("attendance:dispute_attachment", args=[dispute.pk])).status_code == 403
    url = reverse("attendance:disputes")
    page = client.get(url)
    assert page.context["page_obj"].paginator.count == 0
    assert client.post(url, {"dispute_id": dispute.pk, "action": "fix"}).status_code in (200, 403)
    dispute.refresh_from_db()
    assert dispute.status == DisputeStatus.OPEN
    assert client.post(url, {"dispute_id": dispute.pk, "action": "delete"}).status_code in (200, 403)
    assert Dispute.objects.filter(pk=dispute.pk).exists()


def test_deletion_requires_post_and_csrf(sample, absent):
    dispute = sample.services.disputes.create(sample.member, absent.pk, "Заявка")
    client = Client(enforce_csrf_checks=True)
    client.force_login(sample.teacher.user)
    url = reverse("attendance:disputes")
    response = client.get(url, {"action": "delete", "dispute_id": dispute.pk})
    assert Dispute.objects.filter(pk=dispute.pk).exists()
    data = {"action": "delete", "dispute_id": dispute.pk}
    assert client.post(url, data).status_code == 403
    data["csrfmiddlewaretoken"] = response.cookies["csrftoken"].value
    assert client.post(url, data, HTTP_ORIGIN="https://foreign.example").status_code == 403
    assert client.post(url, data, HTTP_ORIGIN="http://testserver").status_code == 302
    assert not Dispute.objects.filter(pk=dispute.pk).exists()


def test_open_request_blocks_duplicate_form_and_missing_attachment_is_404(client, sample, absent):
    dispute = sample.services.disputes.create(sample.member, absent.pk, "Без документа")
    client.force_login(sample.member.user)
    response = client.get(reverse("attendance:absence", args=[absent.pk]))
    assert response.context["has_open_dispute"]
    assert "уже отправлена" in response.content.decode()
    assert client.get(reverse("attendance:dispute_attachment", args=[dispute.pk])).status_code == 404


def test_web_reject_requires_comment_and_preserves_absence(client, sample, absent):
    dispute = sample.services.disputes.create(sample.member, absent.pk, "Заявка")
    client.force_login(sample.teacher.user)
    url = reverse("attendance:disputes")
    assert client.post(url, {"dispute_id": dispute.pk, "action": "reject"}).status_code == 200
    dispute.refresh_from_db()
    assert dispute.status == DisputeStatus.OPEN
    assert client.post(url, {"dispute_id": dispute.pk, "action": "reject", "comment": "Не подходит"}).status_code == 302
    absent.refresh_from_db()
    assert absent.status == S.ABSENT


def test_link_page_preserves_same_origin_and_requires_valid_csrf(sample, settings):
    settings.TELEGRAM_BOT_TOKEN = "offline-test-token"
    settings.TELEGRAM_BOT_USERNAME = "offline_test_bot"
    client = Client(enforce_csrf_checks=True)
    client.force_login(sample.member.user)
    url = reverse("attendance:telegram")
    response = client.get(url)
    assert response["Referrer-Policy"] == "same-origin"
    assert response["Cache-Control"] == "no-store"
    assert client.post(url, {"action": "link"}).status_code == 403
    data = {"action": "link", "csrfmiddlewaretoken": response.cookies["csrftoken"].value}
    assert client.post(url, data, HTTP_ORIGIN="null").status_code == 403
    response = client.post(url, data, HTTP_ORIGIN="http://testserver")
    assert response.status_code == 200
    assert response.context["deep_link"].startswith("https://t.me/offline_test_bot?start=")


def test_delegation_page_assigns_and_revokes_with_role_checks(client, sample):
    client.force_login(sample.headman.user)
    url = reverse("attendance:delegation")
    assert client.post(url, {"action": "assign", "delegate_id": sample.member.pk}).status_code == 302
    delegation = sample.member.delegations.get()
    client.force_login(sample.member.user)
    assert client.post(url, {"action": "revoke", "delegation_id": delegation.pk}).status_code == 200
    delegation.refresh_from_db()
    assert delegation.revoked_at is None
    client.force_login(sample.deputy.user)
    assert client.post(url, {"action": "revoke", "delegation_id": delegation.pk}).status_code == 302
    delegation.refresh_from_db()
    assert delegation.revoked_at is not None
