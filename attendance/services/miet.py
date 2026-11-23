"""Публичное расписание МИЭТ → календарь .ics с ФИО преподавателей."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
import re
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event

from attendance.errors import InvalidChangeError


@dataclass(frozen=True)
class ScheduleCalendar:
    content: bytes
    semester: str
    semester_start: date
    source: str


class MietScheduleClient:
    def download(self, group_name: str) -> ScheduleCalendar:
        group_name = group_name.strip()
        if not group_name or len(group_name) > 50:
            raise InvalidChangeError("Укажите название группы МИЭТ")
        url = "https://miet.ru/schedule/data?" + urlencode({"group": group_name})
        try:
            with urlopen(url, timeout=20) as response:
                raw = response.read(5 * 1024 * 1024 + 1)
            if len(raw) > 5 * 1024 * 1024:
                raise InvalidChangeError("Ответ МИЭТ слишком большой")
            return self.build_calendar(json.loads(raw), group_name, url)
        except (URLError, TimeoutError, OSError) as error:
            raise InvalidChangeError("МИЭТ сейчас недоступен. Попробуйте загрузить расписание позже") from error
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise InvalidChangeError("Не удалось разобрать ответ расписания МИЭТ") from error

    def build_calendar(self, payload: dict, group_name: str, source: str = "") -> ScheduleCalendar:
        rows = payload.get("Data", [])
        if not rows:
            raise InvalidChangeError(f"Для группы {group_name} не найдено расписание")
        if not isinstance(rows, list) or len(rows) > 1000:
            raise InvalidChangeError("Некорректный размер расписания")
        term = str(payload.get("Semestr", ""))
        years = re.search(r"(\d{4})\s*/\s*(\d{4})", term)
        if not years:
            raise InvalidChangeError("В ответе МИЭТ не указан учебный год")
        if "Осен" in term:
            start = date(int(years[1]), 9, 1)
            if start.weekday() >= 5:
                start += timedelta(days=7 - start.weekday())
            semester = f"Осень {years[1]}/{years[2]}"
        elif "Весен" in term:
            first_february = date(int(years[2]), 2, 1)
            start = first_february + timedelta(days=(-first_february.weekday()) % 7 + 7)
            semester = f"Весна {years[1]}/{years[2]}"
        else:
            raise InvalidChangeError("Не определен семестр расписания")
        monday = start - timedelta(days=start.weekday())
        patterns = defaultdict(set)
        aliases = {
            "Метрология и электрорадиоизмерения / Метрология, стандартизация и сертификация": "Метрология и электрорадиоизмерения",
            "Операционные системы/Информационные технологии 1. Операционные системы": "Операционные системы",
        }
        for row in rows:
            if str(row["Group"]["Name"]).strip().casefold() != group_name.casefold():
                raise InvalidChangeError("МИЭТ вернул расписание другой группы")
            week, day, slot = int(row["DayNumber"]), int(row["Day"]) - 1, int(row["Time"]["Code"])
            if week not in range(4) or day not in range(7) or not 1 <= slot <= 12:
                raise InvalidChangeError("Некорректный день или номер пары")
            summary = str(row["Class"]["Name"]).strip()
            for original, replacement in aliases.items():
                summary = summary.replace(original, replacement)
            teacher = str(row["Class"].get("TeacherFull", "")).strip()
            room = str(row["Room"]["Name"]).strip()
            from_ = datetime.fromisoformat(row["Time"]["TimeFrom"]).time()
            to = datetime.fromisoformat(row["Time"]["TimeTo"]).time()
            if to <= from_:
                raise InvalidChangeError(f"Некорректное время пары: {summary}")
            patterns[(week, day, summary, teacher, room)].add((slot, from_, to))
        calendar = Calendar()
        calendar.add("prodid", "-//FLAG//MIET schedule//RU")
        calendar.add("version", "2.0")
        calendar.add("x-wr-calname", group_name)
        calendar.add("x-semester", semester)
        calendar.add("x-semester-start", start.isoformat())
        if source:
            calendar.add("x-source", source)
        for (week, day, summary, teacher, room), slots in sorted(patterns.items()):
            merged = []
            for slot, from_, to in sorted(slots):
                if merged and slot == merged[-1][1] + 1 and merged[-1][0] == merged[-1][1]:
                    merged[-1] = (merged[-1][0], slot, merged[-1][2], to)
                else:
                    merged.append((slot, slot, from_, to))
            weeks = [index for index in range(18) if index % 4 == week
                     and monday + timedelta(weeks=index, days=day) >= start]
            if not weeks:
                continue
            for _, _, from_, to in merged:
                first_day = monday + timedelta(weeks=weeks[0], days=day)
                begins = datetime.combine(first_day, from_, ZoneInfo("Europe/Moscow"))
                ends = datetime.combine(first_day, to, ZoneInfo("Europe/Moscow"))
                event = Event()
                event.add("summary", summary)
                event.add("dtstart", begins)
                event.add("dtend", ends)
                event.add("location", room)
                event.add("x-teacher", teacher)
                event.add("x-group", group_name)
                event.add("uid", str(uuid5(NAMESPACE_URL, f"{group_name}|{summary}|{teacher}|{room}|{begins.isoformat()}|{ends.isoformat()}")))
                event.add("rrule", {"freq": "weekly", "interval": 4, "count": len(weeks)})
                calendar.add_component(event)
        return ScheduleCalendar(calendar.to_ical(), semester, start, source)
