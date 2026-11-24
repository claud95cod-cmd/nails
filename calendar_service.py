from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException


def lock(db):
    db.execute("SELECT pg_advisory_xact_lock(714531)")


def quote(db, service, addon=None, addons=()):
    result = dict(service)
    ids = list(addons)
    if addon is not None:
        ids.append(addon)
    if not ids:
        return result
    if len(ids) > 20 or len(set(ids)) != len(ids) or any(not 1 <= value <= 2147483647 for value in ids):
        raise HTTPException(422, "Проверьте дополнения")
    extras = db.execute("""SELECT * FROM addons WHERE service_id=%s AND visible
        AND id = ANY(%s) ORDER BY id""", (service["id"], ids)).fetchall()
    if len(extras) != len(ids):
        raise HTTPException(422, "Дополнение недоступно")
    result["price"] += sum(extra["price"] for extra in extras)
    result["minutes"] += sum(extra["minutes"] for extra in extras)
    result["title"] += " + " + " + ".join(extra["title"] for extra in extras)
    return result


def day_hours(day, weekly, exceptions):
    if day in exceptions:
        return exceptions[day]
    return weekly.get(day.weekday(), (time(10), time(18)))


def rules(db):
    weekly = {r["weekday"]:(r["opens"],r["closes"]) for r in db.execute("SELECT * FROM week_hours")}
    exceptions = {r["day"]:(r["opens"],r["closes"]) for r in db.execute("SELECT * FROM exceptions")}
    return weekly, exceptions


def timeline(db, profile, minutes, skip=None):
    zone = ZoneInfo(profile["timezone"])
    now = datetime.now(zone)
    weekly, exceptions = rules(db)
    busy = db.execute("""SELECT starts,ends,'Занято' AS label FROM visits
        WHERE NOT cancelled AND ends>now() AND id IS DISTINCT FROM %s
        UNION ALL SELECT starts,ends,'Перерыв' FROM breaks WHERE ends>now()""",(skip,)).fetchall()
    result = {}
    for offset in range(profile["horizon"]):
        day = now.date()+timedelta(days=offset)
        hours = day_hours(day, weekly, exceptions)
        options = result[day.isoformat()] = []
        if hours[0] is None:
            continue
        start = datetime.combine(day,hours[0],zone)
        close = datetime.combine(day,hours[1],zone)
        duration = timedelta(minutes=minutes)
        while start+duration <= close:
            if start > now:
                label = next((v["label"] for v in busy if start<v["ends"] and start+duration>v["starts"]), "")
                options.append({"start":start.isoformat(),"status":label})
            start += timedelta(minutes=profile["step"])
    return result


def available(days):
    return [o["start"] for options in days.values() for o in options if not o["status"]]
