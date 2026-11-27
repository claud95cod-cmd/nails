from main import PRIVACY_VERSION
import os
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from main import app
from storage import connect
from sample_catalog import initialize


@pytest.fixture
def c():
    assert os.getenv("TEST_DISPOSABLE_DATABASE")=="1"
    initialize()
    client=TestClient(app,base_url="https://testserver",headers={"origin":"https://testserver"})
    assert client.post("/admin/login",json={"password":os.environ["TEST_MASTER_PASSWORD"]}).status_code==200
    return client


def test_schedule_cycle(c):
    with connect() as db:
        occupied={r["day"] for r in db.execute("SELECT DISTINCT (starts AT TIME ZONE 'Europe/Astrakhan')::date AS day FROM visits")}
    today=datetime.now(ZoneInfo("Europe/Astrakhan")).date()
    day=next(candidate.isoformat() for offset in range(1,30)
             if (candidate:=today+timedelta(days=offset)) not in occupied)
    def rule(kind,**values):
        return c.post("/admin/rules",json=dict(day=day,kind=kind,**values))
    assert rule("settings",step=15).is_success
    assert rule("break",opens="13:00",closes="14:00").is_success
    def choices():
        return {x["start"][11:16]:x for x in c.get("/slots?addon=1").json()["days"][day]}
    times=choices()
    assert times["11:15"]["status"]==times["16:15"]["status"]==""
    assert times["11:30"]["status"]=="Перерыв" and "16:30" not in times
    def book(hour):
        return c.post("/admin/book",json=dict(name="Клиент",phone="+70000000011",addon=1,
            price=2300,social="Telegram @client",starts=times[hour]["start"],request_id=str(uuid.uuid4())))
    visit=book("11:15").json()["url"]
    assert book("16:15").is_success
    with connect() as db:
        row=db.execute("SELECT id FROM visits WHERE token=%s",(visit.split("/")[-1],)).fetchone()
    key=str(row["id"])
    assert "Telegram @client" in c.get("/admin?visit="+key).text
    assert "Telegram @client" not in c.get(visit).text
    assert choices()["11:15"]["status"]=="Занято"
    assert rule("date",off=True).status_code==409
    assert rule("break",opens="11:00",closes="12:00").status_code==409
    def move(hour):
        return c.post("/admin/move/"+key,json={"starts":times[hour]["start"]})
    assert move("16:15").status_code==409 and "11:15" in c.get(visit).text
    assert move("14:00").is_success and "14:00" in c.get(visit).text
    assert c.post("/admin/cancel/"+key).is_success
    assert "Запись отменена" in c.get(visit).text and choices()["14:00"]["status"]==""
    assert book("14:00").is_success
    assert rule("settings",step=60).is_success


def test_block_races_with_online_booking(c):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    day=(datetime.now(ZoneInfo("Europe/Astrakhan")).date()+timedelta(days=8)).isoformat()
    slot=c.get("/slots").json()["days"][day][0]["start"]
    barrier=Barrier(2)
    def write(kind):
        barrier.wait()
        if kind=="break":
            return c.post("/admin/rules",json=dict(kind="break",day=day,opens="10:30",closes="11:30")).status_code
        return c.post("/book",json=dict(consent_version=PRIVACY_VERSION,name="Проверка",phone="+70000000001",price=2000,
            starts=slot,request_id=str(uuid.uuid4()))).status_code
    with ThreadPoolExecutor(2) as executor:
        assert sorted(executor.map(write,["break","visit"]))==[200,409]


def test_prebooking_and_batch(c):
    slot = c.get("/slots").json()["times"][0]
    day = slot[:10]
    def apply(*edits):
        return c.post("/admin/schedule-changes", json={"day":day, "edits":list(edits)})
    def setting(hours):
        return dict(day=day, kind="settings", step=60, horizon=30, lead_hours=hours)
    assert apply(setting(168), dict(day=day, kind="date", opens="18:00", closes="10:00")).status_code == 422
    assert slot in c.get("/slots").json()["times"]
    try:
        assert apply(setting(168)).is_success
        assert slot not in c.get("/slots").json()["times"]
        assert slot in c.get("/admin/slots").json()["times"]
        result = c.post("/book",json=dict(consent_version=PRIVACY_VERSION,name="Клиент",phone="+70000000011",price=2000,
            starts=slot,request_id=str(uuid.uuid4())))
        assert result.status_code == 409
    finally:
        assert apply(setting(0)).is_success
