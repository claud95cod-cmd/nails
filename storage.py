import os
from datetime import datetime, timedelta, time
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parent


def connect():
    db = psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row,
                         prepare_threshold=None, connect_timeout=8)
    db.execute("SET LOCAL search_path=booking,pg_catalog")
    return db


def initialize(demo=True):
    with connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(714531)")
        db.execute((ROOT / "schema.sql").read_text("utf-8"))
        inserted = db.execute("""INSERT INTO profile(id,name,address,phone,timezone,directions,specialty)
            VALUES (1,'Онлайн-запись','','','Europe/Ulyanovsk','','')
            ON CONFLICT DO NOTHING RETURNING id""").fetchone()
        if demo and inserted:
            from starter import apply_starter, load_starter
            apply_starter(db, *load_starter(ROOT / "starter-kit/ulyanovsk/profile.json"))


def windows(db, profile, service):
    zone = ZoneInfo(profile["timezone"])
    now = datetime.now(zone)
    busy = db.execute("SELECT starts, ends FROM visits WHERE ends > now() ORDER BY starts").fetchall()
    length = timedelta(minutes=service["minutes"])
    result = []
    for offset in range(30):
        day = now.date() + timedelta(days=offset)
        start = datetime.combine(day, time(10), zone)
        close = start.replace(hour=18)
        while start + length <= close:
            if start > now and all(start >= v["ends"] or start + length <= v["starts"] for v in busy):
                result.append(start)
            start += timedelta(minutes=15)
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--empty", action="store_true", help="Создать экземпляр без демонстрационного содержимого")
    initialize(demo=not parser.parse_args().empty)
