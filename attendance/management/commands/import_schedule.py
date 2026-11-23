from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from attendance.models import Group
from attendance.services.schedule_import import ScheduleImporter


class Command(BaseCommand):
    help = "Однократно импортировать календарь .ics в существующую группу"

    def add_arguments(self, parser):
        parser.add_argument("group")
        parser.add_argument("file", type=Path)
        parser.add_argument("--semester", required=True)

    def handle(self, *args, **options):
        try:
            group = Group.objects.get(name=options["group"])
            with options["file"].open("rb") as source:
                result = ScheduleImporter().import_ics(source, group.pk, semester=options["semester"])
        except (Group.DoesNotExist, OSError) as error:
            raise CommandError(str(error)) from error
        if result.errors:
            raise CommandError("; ".join(result.errors))
        self.stdout.write(self.style.SUCCESS(f"Создано занятий: {result.created}; пропущено служебных: {result.skipped}"))
