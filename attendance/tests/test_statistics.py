from datetime import timedelta

import pytest

from attendance.errors import AccessDeniedError, InvalidChangeError
from attendance.models import AttendanceRecord, AttendanceStatus as S, Lesson, LessonType
from attendance.services.calculator import AttendanceCalculator as Calculator, WarningLevel


@pytest.mark.parametrize(("allowed", "level"), [(2, WarningLevel.OK), (1, WarningLevel.WARNING),
                                                (0, WarningLevel.WARNING), (-1, WarningLevel.BELOW_THRESHOLD)])
def test_warning_boundaries(allowed, level):
    assert Calculator.get_level(allowed) == level


@pytest.mark.parametrize(("marked", "missed", "expected"), [(0, 0, 100), (3, 1, 66), (3, 3, 0)])
def test_current_percent(marked, missed, expected):
    assert Calculator.current_percent(marked, missed) == expected


@pytest.mark.django_db
def test_statistics_include_future_lessons_but_only_started_unmarked(sample):
    Lesson.objects.create(course=sample.course, start_at=sample.now + timedelta(days=1),
                          end_at=sample.now + timedelta(days=1, minutes=80), type=LessonType.LAB)
    report = sample.services.statistics.for_student(sample.member,
        sample.now - timedelta(days=1), sample.now + timedelta(days=2))[0]
    assert report.course == sample.course
    assert (report.total.total, report.total.marked, report.total.not_marked) == (2, 0, 1)
    assert report.total.allowed_misses == 1
    assert set(report.by_type) == {LessonType.LECTURE, LessonType.LAB}


@pytest.mark.django_db
def test_half_open_period_excludes_lesson_at_end(sample):
    assert sample.services.statistics.for_student(sample.member,
        sample.lesson.start_at - timedelta(days=1), sample.lesson.start_at) == []


@pytest.mark.django_db
def test_foreign_teacher_cannot_read_course_history_or_change_threshold(sample):
    record = AttendanceRecord.objects.create(lesson=sample.lesson, student=sample.member)
    with pytest.raises(AccessDeniedError):
        sample.services.statistics.for_course(sample.foreign_teacher, sample.course,
                                              sample.now - timedelta(days=1), sample.now + timedelta(days=1))
    with pytest.raises(AccessDeniedError):
        sample.services.statistics.get_record_history(sample.foreign_teacher, record.pk)
    with pytest.raises(AccessDeniedError):
        sample.services.courses.set_threshold(sample.foreign_teacher, sample.course.pk, 70)


@pytest.mark.django_db
def test_teacher_report_detects_partially_marked_lesson(sample):
    sample.services.attendance.save_marks(sample.headman, sample.lesson.pk,
        {sample.member.pk: S.PRESENT}, expected_version=0)
    report = sample.services.statistics.for_course(sample.teacher, sample.course,
        sample.now - timedelta(days=1), sample.now + timedelta(days=1))
    assert report.unmarked_lessons == [sample.lesson]
    assert len(report.rows) == 3
    assert sample.services.attendance.get_unmarked_lessons(sample.headman) == [sample.lesson]


@pytest.mark.django_db
@pytest.mark.parametrize("percent", [0, 50, 100])
def test_teacher_can_set_threshold(sample, percent):
    sample.services.courses.set_threshold(sample.teacher, sample.course.pk, percent)
    sample.course.refresh_from_db()
    assert sample.course.threshold_percent == percent


@pytest.mark.django_db
@pytest.mark.parametrize("percent", [-1, 101, True, 50.5])
def test_threshold_invalid_values(sample, percent):
    with pytest.raises(ValueError):
        sample.services.courses.set_threshold(sample.teacher, sample.course.pk, percent)


@pytest.mark.django_db
def test_invalid_period(sample):
    with pytest.raises(InvalidChangeError):
        sample.services.statistics.for_student(sample.member, sample.now, sample.now)
