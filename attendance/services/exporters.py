"""CSV и XLSX используют одни и те же строки отчета преподавателя."""
import csv
from datetime import timedelta
from io import BytesIO, StringIO

from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from attendance.models import LessonType
from .interfaces import IReportExporter
from .reports import CourseReport


def _display_text(value):
    return value.translate(str.maketrans("\u0451\u0401", "\u0435\u0415", "\u00b7")) if isinstance(value, str) else value


def _table(report):
    headers = ["ФИО", "Всего", "Был", "Не был", "Без отметки", "Посещаемость, %", "Допустимо пропусков"]
    for kind in LessonType:
        headers.extend([f"{kind.label}: был", f"{kind.label}: не был"])
    headers.append("Причины пропусков")
    rows = []
    for row in report.rows:
        stats = row.total
        values = [f"{row.student.user.last_name} {row.student.user.first_name}".strip(),
                  stats.total, stats.present, stats.missed, stats.not_marked,
                  stats.percent if stats.marked else "", stats.allowed_misses]
        for kind in LessonType:
            kind_stats = row.by_type.get(kind)
            values.extend([kind_stats.present if kind_stats else 0, kind_stats.missed if kind_stats else 0])
        rows.append(values + ["; ".join(row.reasons)])
    return headers, rows


def _period(report):
    return (f"{timezone.localtime(report.from_):%d.%m.%Y} — "
            f"{(timezone.localtime(report.to) - timedelta(days=1)):%d.%m.%Y}")


class CsvExporter(IReportExporter):
    @property
    def format(self) -> str:
        return "csv"

    def export(self, report: CourseReport) -> bytes:
        """Модуль csv; кодировка utf-8-sig, разделитель «;» - чтобы Excel открыл кириллицу."""
        stream = StringIO(newline="")
        writer = csv.writer(stream, delimiter=";")
        def safe(values):
            values = [_display_text(value) for value in values]
            return ["'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@"))
                    else value for value in values]
        writer.writerow(safe([report.course.subject.name, report.course.group.name, report.course.semester]))
        writer.writerow(["Период", _period(report), "Порог, %", report.course.threshold_percent])
        headers, rows = _table(report)
        writer.writerow(headers)
        writer.writerows(safe(row) for row in rows)
        writer.writerow([])
        writer.writerow(["Занятия с неполной отметкой"])
        for lesson in report.unmarked_lessons:
            writer.writerow(safe([f"{timezone.localtime(lesson.start_at):%d.%m.%Y %H:%M}", lesson.get_type_display(), lesson.room]))
        return stream.getvalue().encode("utf-8-sig")


class XlsxExporter(IReportExporter):
    @property
    def format(self) -> str:
        return "xlsx"

    def export(self, report: CourseReport) -> bytes:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Посещаемость"
        sheet.append([report.course.subject.name, report.course.group.name, report.course.semester])
        sheet.append(["Период", _period(report), "Порог, %", report.course.threshold_percent])
        sheet.append([])
        headers, rows = _table(report)
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
        for cell in sheet[4]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="285CE6")
        sheet.freeze_panes = "B5"
        sheet.auto_filter.ref = f"A4:{sheet.cell(sheet.max_row, sheet.max_column).coordinate}"
        sheet.column_dimensions["A"].width = 38
        for column in range(2, sheet.max_column + 1):
            sheet.column_dimensions[sheet.cell(4, column).column_letter].width = 21
        unmarked = workbook.create_sheet("Без отметки")
        unmarked.append(["Дата", "Тип занятия", "Аудитория"])
        for lesson in report.unmarked_lessons:
            unmarked.append([f"{timezone.localtime(lesson.start_at):%d.%m.%Y %H:%M}", lesson.get_type_display(), lesson.room])
        for column in ("A", "B", "C"):
            unmarked.column_dimensions[column].width = 25
        for page in workbook:
            for row in page:
                for cell in row:
                    if isinstance(cell.value, str):
                        cell.value = _display_text(cell.value)
                        cell.data_type = "s"
        output = BytesIO()
        workbook.save(output)
        return output.getvalue()


class PdfExporter(IReportExporter):
    @property
    def format(self) -> str:
        return "pdf"

    def export(self, report: CourseReport) -> bytes:
        """Опционально по ТЗ (5.5); понадобится reportlab или аналог."""
        raise NotImplementedError("ЛР4")


EXPORTERS: dict[str, IReportExporter] = {e.format: e for e in (CsvExporter(), XlsxExporter(), PdfExporter())}
