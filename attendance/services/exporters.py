"""Экспорт отчёта преподавателя (IReportExporter)."""
from .interfaces import IReportExporter
from .reports import CourseReport


class CsvExporter(IReportExporter):
    @property
    def format(self) -> str:
        return "csv"

    def export(self, report: CourseReport) -> bytes:
        """Модуль csv; кодировка utf-8-sig, разделитель «;» - чтобы Excel открыл кириллицу."""
        raise NotImplementedError("ЛР4")


class XlsxExporter(IReportExporter):
    @property
    def format(self) -> str:
        return "xlsx"

    def export(self, report: CourseReport) -> bytes:
        """Понадобится openpyxl."""
        raise NotImplementedError("ЛР4")


class PdfExporter(IReportExporter):
    @property
    def format(self) -> str:
        return "pdf"

    def export(self, report: CourseReport) -> bytes:
        """Опционально по ТЗ (5.5); понадобится reportlab или аналог."""
        raise NotImplementedError("ЛР4")


EXPORTERS: dict[str, IReportExporter] = {e.format: e for e in (CsvExporter(), XlsxExporter(), PdfExporter())}
