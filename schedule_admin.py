import uuid
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import BaseModel, Field

from calendar_service import available, day_hours, lock, rules, timeline
from storage import connect


class ScheduleRule(BaseModel):
    kind: str
    day: date
    opens: time|None = None
    closes: time|None = None
    off: bool = False
    step: int = Field(default=60,ge=1,le=1440)
    horizon: int = Field(default=30,ge=1,le=180)


def save_rule(form):
    with connect() as db:
        lock(db)
        p=db.execute("SELECT * FROM profile WHERE id=1").fetchone()
        zone=ZoneInfo(p["timezone"])
        if form.kind=="settings":
            db.execute("UPDATE profile SET step=%s,horizon=%s WHERE id=1",(form.step,form.horizon))
            return
        if form.kind not in {"week","date","break"}:
            raise HTTPException(422,"Неизвестное правило")
        off=form.off and form.kind!="break"
        if not off and (not form.opens or not form.closes or form.opens>=form.closes):
            raise HTTPException(422,"Окончание должно быть позже начала")
        if form.kind=="break":
            start=datetime.combine(form.day,form.opens,zone)
            end=datetime.combine(form.day,form.closes,zone)
            conflict=db.execute("SELECT 1 FROM visits WHERE NOT cancelled AND starts<%s AND ends>%s",(end,start)).fetchone()
            if conflict:
                raise HTTPException(409,"На это время есть запись. Сначала перенесите или отмените визит.")
            db.execute("INSERT INTO breaks VALUES (%s,%s,%s)",(uuid.uuid4(),start,end))
            return
        hours=(None,None) if off else (form.opens,form.closes)
        if form.kind=="week":
            db.execute("""INSERT INTO week_hours VALUES (%s,%s,%s) ON CONFLICT(weekday)
                DO UPDATE SET opens=excluded.opens,closes=excluded.closes""",(form.day.weekday(),*hours))
        else:
            db.execute("""INSERT INTO exceptions VALUES (%s,%s,%s) ON CONFLICT(day)
                DO UPDATE SET opens=excluded.opens,closes=excluded.closes""",(form.day,*hours))
        weekly,exceptions=rules(db)
        for v in db.execute("SELECT starts,ends FROM visits WHERE NOT cancelled AND ends>now()"):
            start,end=v["starts"].astimezone(zone),v["ends"].astimezone(zone)
            opens,closes=day_hours(start.date(),weekly,exceptions)
            if opens is None or start.time()<opens or end.time()>closes:
                raise HTTPException(409,"Правило задевает запись. Сначала перенесите или отмените визит.")


def visit_options(db, visit):
    row=db.execute("SELECT * FROM visits WHERE id=%s FOR UPDATE",(visit,)).fetchone()
    if not row or row["cancelled"]:
        raise HTTPException(409,"Визит отменён или отсутствует")
    profile=db.execute("SELECT * FROM profile WHERE id=1").fetchone()
    return available(timeline(db,profile,row["minutes"],visit))


def change_visit(visit, start):
    with connect() as db:
        lock(db)
        if start is None:
            if not db.execute("UPDATE visits SET cancelled=true WHERE id=%s RETURNING id",(visit,)).fetchone():
                raise HTTPException(404,"Запись не найдена")
            return
        if start.isoformat() not in visit_options(db,visit):
            raise HTTPException(409,"Окно занято. Исходная запись сохранена.")
        db.execute("UPDATE visits SET starts=%s, ends=%s+make_interval(mins=>minutes) WHERE id=%s",
                   (start,start,visit))
