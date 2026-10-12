"""Ядро приложения (UML/class_services.puml) поверх Django-моделей.

Сайт и бот обращаются к ядру только через эти сервисы. Сервисы загружают
модели, проверяют права (AccessPolicy), вызывают методы моделей
(change, resolve, revoke...) и рассылают уведомления.

Сборка с зависимостями - build_services(); в тестах можно подменить часы и канал:
    services = build_services(clock=FakeClock(...), channel=FakeChannel())
"""
from dataclasses import dataclass

from .attendance import AttendanceService
from .calculator import AttendanceCalculator, AttendanceStats, WarningLevel
from .clock import DjangoClock
from .courses import CourseService
from .delegation import DelegationService
from .disputes import DisputeService
from .exporters import EXPORTERS, CsvExporter, PdfExporter, XlsxExporter
from .interfaces import IClock, INotificationChannel, IReportExporter
from .notifications import NotificationService, NullChannel
from .policy import AccessPolicy
from .reports import CourseReport, ReportRow
from .schedule_import import ImportResult, ScheduleImporter
from .statistics import StatisticsService
from .telegram_link import TelegramLinkService


@dataclass(frozen=True)
class Services:
    attendance: AttendanceService
    disputes: DisputeService
    delegation: DelegationService
    courses: CourseService
    statistics: StatisticsService
    telegram_link: TelegramLinkService
    notifications: NotificationService


def build_services(clock: IClock | None = None, channel: INotificationChannel | None = None) -> Services:
    clock = clock or DjangoClock()
    policy = AccessPolicy()
    notifications = NotificationService(clock, channel or NullChannel())
    statistics = StatisticsService(clock, policy)
    attendance = AttendanceService(clock, policy, statistics, notifications)
    return Services(
        attendance=attendance,
        disputes=DisputeService(clock, policy, attendance, notifications),
        delegation=DelegationService(clock, policy, notifications),
        courses=CourseService(policy),
        statistics=statistics,
        telegram_link=TelegramLinkService(clock),
        notifications=notifications,
    )
