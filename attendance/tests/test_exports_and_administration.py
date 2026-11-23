import csv
from datetime import timedelta
from io import BytesIO, StringIO

from openpyxl import load_workbook
import pytest

from attendance.admin_forms import StudentManagementForm, TeacherManagementForm
from attendance.errors import AccessDeniedError
from attendance.models import AttendanceRecord, AttendanceStatus as S, Teacher, User
from attendance.services.administration import AdministrationService
from attendance.services.exporters import CsvExporter, XlsxExporter

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@"])
def test_csv_and_xlsx_preserve_counts_and_prevent_formula_execution(sample, prefix):
    sample.member.user.last_name = prefix + "Тест"
    sample.member.user.save(update_fields=["last_name"])
    AttendanceRecord.objects.create(lesson=sample.lesson, student=sample.member, status=S.PRESENT)
    report = sample.services.statistics.for_course(sample.teacher, sample.course,
        sample.now - timedelta(days=1), sample.now + timedelta(days=1))
    output = CsvExporter().export(report)
    assert output.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(StringIO(output.decode("utf-8-sig")), delimiter=";"))
    student_row = next(row for row in rows if row and row[0].startswith("'" + prefix))
    assert student_row[1:6] == ["1", "1", "0", "0", "100"]
    workbook = load_workbook(BytesIO(XlsxExporter().export(report)))
    cells = [row[0] for row in workbook.worksheets[0].iter_rows(min_row=5)]
    cell = next(cell for cell in cells if str(cell.value).startswith(prefix))
    assert cell.data_type == "s"
    assert workbook.worksheets[0].cell(cell.row, 3).value == 1
    assert "Без отметки" in workbook.sheetnames


def test_profile_creation_change_and_duplicate_username(sample):
    data = {"username": "new_student", "last_name": "Иванов", "first_name": "Иван Иванович", "role": "MEMBER"}
    form = StudentManagementForm(data)
    assert form.is_valid(), form.errors
    student = form.save(commit=False)
    student.group = sample.group
    student.save()
    assert student.user.check_password("1234")
    data["last_name"] = "Петров"
    changed = StudentManagementForm(data, instance=student)
    assert changed.is_valid(), changed.errors
    changed.save()
    student.user.refresh_from_db()
    assert student.user.last_name == "Петров"
    assert student.user.check_password("1234")
    duplicate = StudentManagementForm(data)
    assert not duplicate.is_valid()
    assert "username" in duplicate.errors


def test_teacher_creation_and_course_assignment(sample):
    form = TeacherManagementForm({"username": "new_teacher", "last_name": "Сидоров",
        "first_name": "Игорь Иванович", "password": "teacher-test-password", "courses": [sample.course.pk]})
    assert form.is_valid(), form.errors
    teacher = form.save()
    assert teacher.courses.get() == sample.course
    assert teacher.user.check_password("teacher-test-password")


def test_administration_requires_staff_and_preserves_authors_on_teacher_deletion(sample):
    service = AdministrationService()
    with pytest.raises(AccessDeniedError):
        service.delete_teacher(sample.member.user, sample.teacher)
    admin = User.objects.create_user("technical_admin", is_staff=True)
    record = AttendanceRecord.objects.create(lesson=sample.lesson, student=sample.member)
    record.change(S.ABSENT, sample.headman, "", sample.now)
    dispute = sample.services.disputes.create(sample.member, record.pk, "Проверьте")
    sample.services.disputes.resolve(sample.teacher, dispute.pk, True)
    user_id = sample.teacher.user_id
    service.delete_teacher(admin, sample.teacher)
    assert not Teacher.objects.filter(pk=sample.teacher.pk).exists()
    author = User.objects.get(pk=user_id)
    assert not author.is_active
    assert record.changes.latest("pk").changed_by_id == user_id


def test_group_deletion_removes_group_data_but_preserves_teacher(sample):
    service = AdministrationService()
    admin = User.objects.create_user("technical_admin", is_staff=True)
    group_id, teacher_id = sample.group.pk, sample.teacher.pk
    with pytest.raises(AccessDeniedError):
        service.delete_group(sample.member.user, sample.group)
    service.delete_group(admin, sample.group)
    assert not sample.group.__class__.objects.filter(pk=group_id).exists()
    assert Teacher.objects.filter(pk=teacher_id).exists()
