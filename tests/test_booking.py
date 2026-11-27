from main import PRIVACY_VERSION
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

import push
from main import app
from storage import connect, initialize

@pytest.fixture(scope="module")
def client():
    if os.getenv("TEST_DISPOSABLE_DATABASE")!="1":
        pytest.skip("Требуется одноразовая тестовая база")
    initialize()
    return TestClient(app,base_url="https://testserver",headers={"Origin":"https://testserver"})


def payload(c):
    data=c.get("/slots").json()
    return dict(consent_version=PRIVACY_VERSION,name="Тест", phone="+70000000001",price=data["price"], starts=data["times"][0],request_id=str(uuid.uuid4()))


def test_path_and_retry(client):
    assert "Студия Лины" in client.get("/").text
    item=payload(client)
    assert client.get("/privacy").status_code == 200
    assert client.post("/book",json={**item,"consent_version":None}).status_code == 422
    assert client.post("/book",json={**item,"consent_version":"old"}).status_code == 422
    r=client.post("/book",json=item)
    assert r.status_code==200
    assert client.post("/book",json=item).json()==r.json()
    private=client.get(r.json()["url"])
    assert "Вы записаны" in private.text and item["phone"] not in private.text
    assert private.headers["cache-control"]=="no-store"
    assert item["starts"] not in client.get("/slots").json()["times"]
    assert "Войти" in client.get("/admin").text
    assert client.post("/admin/login",json={"password":os.environ["TEST_MASTER_PASSWORD"]}).status_code==200
    with connect() as db:
        event=db.execute("SELECT visit FROM events").fetchone()
    assert item["phone"] in client.get("/admin",params={"visit":event["visit"]}).text


def test_storefront_time_first(client, monkeypatch):
    monkeypatch.delenv("MASTER_CABINET_ENABLED", raising=False)
    assert "Кабинет мастера" in client.get("/admin").text
    monkeypatch.setenv("MASTER_CABINET_ENABLED", "0")
    page = client.get("/")
    assert page.status_code == 200
    assert "Ближайшая запись" in page.text and 'href="/admin' not in page.text
    assert client.get("/admin").status_code == 404
    assert client.post("/admin/login", json={}).status_code == 404

    first = client.get("/windows").json()["times"][0]
    assert f'data-start="{first}"' in page.text
    item = payload(client)
    booked = client.post("/book", json=item)
    assert booked.status_code == 200
    assert client.get(booked.json()["url"]).status_code == 200
    assert item["starts"] not in client.get("/windows").json()["times"]


def test_race(client):
    item=payload(client)
    with ThreadPoolExecutor(2) as executor:
        results=list(executor.map(lambda _:client.post("/book",json={**item,"request_id":str(uuid.uuid4())}).status_code,range(2)))
    assert sorted(results)==[200,409]


def test_price_and_origin(client):
    item=payload(client)
    assert client.post("/book",json={**item,"price":1}).status_code==409
    assert client.post("/book",json=item,headers={"Origin":"https://other.invalid"}).status_code==403


def test_queue(client,monkeypatch):
    sub=dict(endpoint="https://fcm.googleapis.com/test",keys={"auth":"a"*22,"p256dh":"b"*87})
    assert client.post("/admin/login",json={"password":os.environ["TEST_MASTER_PASSWORD"]}).status_code==200
    assert client.post("/admin/device/enable",json=sub).status_code==200
    assert client.post("/book",json=payload(client)).status_code==200
    def offline(*args,**kwargs):
        raise push.WebPushException("Временно недоступно")
    monkeypatch.setattr(push,"webpush",offline)
    assert push.deliver_one()
    with connect() as db:
        row=db.execute("SELECT attempts,accepted,due>now() AS delayed FROM deliveries").fetchone()
        assert row==dict(attempts=1,accepted=None,delayed=True)
        db.execute("UPDATE deliveries SET due=now()")
    sent=[]
    monkeypatch.setattr(push,"webpush",lambda *args,**kwargs:sent.append(args[1]))
    assert push.deliver_one() and not push.deliver_one()
    assert "70000000001" not in sent[0]
