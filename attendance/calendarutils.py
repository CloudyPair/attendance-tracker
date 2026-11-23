"""Обозначения четырехнедельного цикла исходного календаря МИЭТ."""
from datetime import datetime, timedelta
import json

from django.conf import settings


def academic_week_type(day, group_name, group_id=None):
    try:
        metadata_path = settings.MEDIA_ROOT / "schedules" / f"{group_id}.json"
        saved_for_group = metadata_path.exists()
        if not saved_for_group:
            metadata_path = settings.BASE_DIR / "data" / "ivt31_source.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not saved_for_group and metadata["group"] != group_name:
            return ""
        semester_start = datetime.strptime(metadata["semester_start"], "%d-%m-%Y").date()
    except (OSError, ValueError, KeyError, TypeError):
        return ""
    first_monday = semester_start - timedelta(days=semester_start.weekday())
    week_index = (day - first_monday).days // 7
    return ("Ч-1", "З-1", "Ч-2", "З-2")[week_index % 4] if 0 <= week_index < 18 else ""
