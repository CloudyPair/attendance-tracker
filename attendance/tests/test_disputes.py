"""Приемочные проверки заявки, документов, решения и удаления спора."""
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from attendance.errors import AccessDeniedError, InvalidChangeError, ReasonRequiredError
from attendance.models import AttendanceRecord, AttendanceStatus as S, ChangeSource, Dispute, DisputeStatus, Lesson

pytestmark = pytest.mark.django_db


@pytest.fixture
def absent(sample):
    record = AttendanceRecord.objects.create(lesson=sample.lesson, student=sample.member)
    record.change(S.ABSENT, sample.headman, "", sample.now)
    return record


def test_request_keeps_absent_until_assigned_teacher_accepts(sample, absent):
    service = sample.services.disputes
    dispute = service.create(sample.member, absent.pk, "Присутствовал, приложил справку",
        SimpleUploadedFile("proof.pdf", b"%PDF-offline-proof", content_type="application/pdf"))
    absent.refresh_from_db()
    assert absent.status == S.ABSENT
    assert dispute.attachment.open("rb").read() == b"%PDF-offline-proof"
    sample.clock.moment += timedelta(days=2)
    service.resolve(sample.teacher, dispute.pk, True)
    absent.refresh_from_db()
    dispute.refresh_from_db()
    assert (absent.status, dispute.status) == (S.PRESENT, DisputeStatus.FIXED)
    assert dispute.resolved_by == sample.teacher.user
    entry = absent.changes.latest("pk")
    assert (entry.changed_by, entry.source) == (sample.teacher.user, ChangeSource.DISPUTE)
    assert sample.services.statistics.for_student_course(sample.member, sample.course).present == 1


@pytest.mark.parametrize("actor", ["headman", "deputy", "member", "outsider", "foreign_teacher"])
def test_students_and_foreign_teachers_cannot_decide_or_delete(sample, absent, actor):
    service = sample.services.disputes
    dispute = service.create(sample.member, absent.pk, "Ошибка отметки")
    user = getattr(sample, actor)
    assert not service.can_resolve(user, dispute)
    assert not service.can_delete(user, dispute)
    with pytest.raises(AccessDeniedError):
        service.resolve(user, dispute.pk, True)
    with pytest.raises(AccessDeniedError):
        service.delete(user, dispute.pk)
    assert Dispute.objects.filter(pk=dispute.pk, status=DisputeStatus.OPEN).exists()
    absent.refresh_from_db()
    assert absent.status == S.ABSENT


@pytest.mark.parametrize("text", ["", "   ", "x" * 2001])
def test_request_needs_explanation(sample, absent, text):
    with pytest.raises(InvalidChangeError):
        sample.services.disputes.create(sample.member, absent.pk, text)
    assert not Dispute.objects.exists()


def test_request_accepts_maximum_text_and_rejects_duplicate(sample, absent):
    service = sample.services.disputes
    service.create(sample.member, absent.pk, "x" * 2000)
    with pytest.raises(InvalidChangeError):
        service.create(sample.member, absent.pk, "Вторая заявка")
    assert Dispute.objects.count() == 1


@pytest.mark.parametrize("owner", ["headman", "outsider"])
def test_cannot_dispute_somebody_elses_record(sample, absent, owner):
    with pytest.raises(AccessDeniedError):
        sample.services.disputes.create(getattr(sample, owner), absent.pk, "Не моя отметка")


@pytest.mark.parametrize("status", [S.PRESENT, S.NOT_MARKED])
def test_only_absences_can_be_disputed(sample, absent, status):
    AttendanceRecord.objects.filter(pk=absent.pk).update(status=status)
    with pytest.raises(InvalidChangeError):
        sample.services.disputes.create(sample.member, absent.pk, "Проверка статуса")


def test_course_without_active_teacher_has_clear_error(sample, absent):
    sample.course.teachers.clear()
    with pytest.raises(InvalidChangeError, match="не назначен преподаватель"):
        sample.services.disputes.create(sample.member, absent.pk, "Ошибка")
    assert not Dispute.objects.exists()


@pytest.mark.parametrize("size,accepted", [(5 * 1024 * 1024, True), (5 * 1024 * 1024 + 1, False)])
def test_attachment_size_boundary(sample, absent, size, accepted):
    upload = SimpleUploadedFile("proof.bin", b"x" * size)
    if accepted:
        assert sample.services.disputes.create(sample.member, absent.pk, "Документ", upload).attachment.size == size
    else:
        with pytest.raises(InvalidChangeError):
            sample.services.disputes.create(sample.member, absent.pk, "Документ", upload)
        assert not Dispute.objects.exists()


def test_rejection_requires_comment_and_does_not_change_attendance(sample, absent):
    service = sample.services.disputes
    dispute = service.create(sample.member, absent.pk, "Проверьте")
    with pytest.raises(ReasonRequiredError):
        service.resolve(sample.teacher, dispute.pk, False, " ")
    dispute.refresh_from_db()
    assert dispute.status == DisputeStatus.OPEN
    service.resolve(sample.teacher, dispute.pk, False, "Документ относится к другой дате")
    absent.refresh_from_db()
    assert absent.status == S.ABSENT
    assert absent.changes.count() == 1
    with pytest.raises(InvalidChangeError):
        service.resolve(sample.teacher, dispute.pk, True)


def test_deletion_preserves_attendance_and_audit_and_allows_new_request(sample, absent):
    service = sample.services.disputes
    dispute = service.create(sample.member, absent.pk, "Пробная заявка")
    service.delete(sample.teacher, dispute.pk)
    absent.refresh_from_db()
    assert (absent.status, absent.changes.count()) == (S.ABSENT, 1)
    assert not Dispute.objects.filter(pk=dispute.pk).exists()
    with pytest.raises(InvalidChangeError):
        service.delete(sample.teacher, dispute.pk)
    assert service.create(sample.member, absent.pk, "Новая заявка").status == DisputeStatus.OPEN


def test_deleting_fixed_dispute_preserves_present_and_teacher_audit(sample, absent):
    service = sample.services.disputes
    dispute = service.create(sample.member, absent.pk, "Проверьте")
    service.resolve(sample.teacher, dispute.pk, True)
    service.delete(sample.teacher, dispute.pk)
    absent.refresh_from_db()
    assert absent.status == S.PRESENT
    assert absent.changes.filter(changed_by=sample.teacher.user, source=ChangeSource.DISPUTE).exists()


def test_visibility_is_own_requests_or_assigned_courses(sample, absent):
    service = sample.services.disputes
    dispute = service.create(sample.member, absent.pk, "Проверьте")
    assert service.list_for(sample.member) == [dispute]
    assert service.list_for(sample.teacher) == [dispute]
    assert service.list_for(sample.headman) == []
    assert service.list_for(sample.foreign_teacher) == []


def test_absences_are_newest_first_with_stable_tie_order(sample, absent):
    later = Lesson.objects.create(course=sample.course, start_at=sample.now + timedelta(days=1),
        end_at=sample.now + timedelta(days=1, minutes=80), type=sample.lesson.type)
    recent = AttendanceRecord.objects.create(lesson=later, student=sample.member, status=S.ABSENT)
    assert [r.pk for r in sample.services.disputes.absences(sample.member)] == [recent.pk, absent.pk]
