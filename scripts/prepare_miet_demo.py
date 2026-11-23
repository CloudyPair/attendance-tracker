"""Сформировать реальный календарь внешним MPSU/schedule_parser, сохранив ФИО.

Запускается вручную; сеть и код внешнего парсера не нужны при seed_demo.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
from urllib.parse import urlencode
from urllib.request import urlopen


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    arguments = argparse.ArgumentParser()
    arguments.add_argument("--parser", type=Path, required=True)
    arguments.add_argument("--snapshot", type=Path)
    arguments.add_argument("--semester-start", default="01-09-2026")
    arguments.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    args = arguments.parse_args()
    source_url = "https://miet.ru/schedule/data?" + urlencode({"group": "ИВТ-31"})
    if args.snapshot:
        payload = json.loads(args.snapshot.read_text(encoding="utf-8-sig"))
    else:
        with urlopen(source_url, timeout=30) as response:
            payload = json.load(response)
    spec = importlib.util.spec_from_file_location("miet_external_parser", args.parser)
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)

    class CachedResponse:
        def json(self):
            return payload

    parser.requests.get = lambda **kwargs: CachedResponse()
    config = dict(parser.DEFAULT_CONFIG, group="ИВТ-31", semester_starts_at=args.semester_start,
                  class_names_cast={"Метрология, стандартизация и сертификация": "Метрология и электрорадиоизмерения",
                                    "Метрология и электрорадиоизмерения / Метрология": "Метрология и электрорадиоизмерения",
                                    "Операционные системы/Информационные технологии 1. Операционные системы": "Операционные системы"})
    entries = parser.merge_list_of_classes(parser.create_list_of_classes_for_student(config))
    calendar = parser.Calendar()
    for entry in entries:
        event = parser.create_icalendar([entry], config).walk("VEVENT")[0]
        names = sorted({row["Class"]["TeacherFull"].strip() for row in payload["Data"]
                        if parser.get_class_name(row["Class"]["Name"], config["class_names_cast"]) == entry.class_name
                        and row["DayNumber"] == entry.week_code and row["Day"] - 1 == entry.week_day
                        and row["Time"]["Code"] - 1 == entry.slot_number
                        and row["Room"]["Name"] == entry.room_number})
        event.add("X-TEACHER", "; ".join(names))
        event.add("X-GROUP", "ИВТ-31")
        calendar.add_component(event)
    calendar = parser.add_weeklies(calendar, config)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "ivt31.ics").write_bytes(calendar.to_ical())
    metadata = {"group": "ИВТ-31", "semester": payload["Semestr"],
                "semester_start": args.semester_start, "source": source_url,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "parser": "https://github.com/MPSU/schedule_parser",
                "parser_revision": "06966377465bc0b685fd35aa65f22bd59c761703",
                "source_entries": len(payload["Data"]), "calendar_entries": len(entries),
                "teacher": "Балабаев Сергей Андреевич",
                "note": "Календарь внешнего парсера; добавлены X-TEACHER и X-GROUP из ответа API. Даты не сдвигались."}
    (args.output / "ivt31_source.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
