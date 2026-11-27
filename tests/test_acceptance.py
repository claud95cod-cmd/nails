from main import PRIVACY_VERSION
import json
import os
import uuid

from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright

import push
from main import app
from starter import import_starter
from storage import connect
from test_instances import KIT, environment, login, picture, running


def public_booking(client):
    quote = client.get("/slots").json()
    return client.post("/book", json={"consent_version": PRIVACY_VERSION,
        "name": "Приёмка push", "phone": "+70000000016", "starts": quote["times"][0],
        "price": quote["price"], "request_id": str(uuid.uuid4()),
    })


def test_hosted_mode(monkeypatch, tmp_path):
    assert os.environ.get("TEST_DISPOSABLE_DATABASE") == "1"
    staging, password = environment(monkeypatch, tmp_path, "hosted", demo=False)
    for key in ("DATABASE_URL", "MEDIA_DIR", "ADMIN_HASH", "CRON_SECRET", "VAPID_PRIVATE", "VAPID_EMAIL"):
        monkeypatch.setenv(key, staging[key])
    monkeypatch.setenv("MEDIA_STORAGE", "postgres")
    import_starter(KIT)
    origin = "https://testserver"
    with TestClient(app, base_url=origin, headers={"origin": origin}) as client:
        assert client.get("/healthz").json() == {"ok": True}
        assert client.post("/admin/login", json={"password": password}).is_success
        new = client.post("/admin/content/photo", content=picture("indigo")).json()["image"]
        assert client.get(f"/media/{new}/thumb").status_code == 404
        assert client.get(f"/admin/content/media/{new}/full").headers["content-type"] == "image/webp"
        work = client.post("/admin/content/work", json={"image": new})
        assert work.is_success
        endpoints = ["https://fcm.googleapis.com/acceptance", "https://web.push.apple.com/acceptance"]
        for endpoint in endpoints:
            assert client.post("/admin/device/enable", json={
                "endpoint": endpoint, "keys": {"auth": "a" * 22, "p256dh": "b" * 87},
            }).is_success
        assert public_booking(client).is_success
        assert client.post("/jobs/push").status_code == 403
        sent = []
        monkeypatch.setattr(push, "webpush", lambda device, payload, **kw:
                            sent.append((device["endpoint"], json.loads(payload))))
        auth = {"Authorization": "Bearer " + staging["CRON_SECRET"]}
        assert client.post("/jobs/push", headers=auth).json() == {"processed": 2}
        assert client.post("/jobs/push", headers=auth).json() == {"processed": 0}
        assert sorted(endpoint for endpoint, _ in sent) == sorted(endpoints)
        for _, payload in sent:
            assert "70000000016" not in payload["body"] and "Приёмка push" not in payload["body"]
            assert payload["url"].startswith("/admin?visit=")
        assert sent[0][1]["tag"] == sent[1][1]["tag"]
    with TestClient(app, base_url=origin) as fresh:
        assert fresh.get(f"/media/{new}/thumb").is_success
        assert fresh.get(f"/admin/content/media/{new}/full").status_code == 401
    assert not (tmp_path / "hosted").exists()
    with connect() as db:
        assert db.execute("SELECT count(*) AS n FROM deliveries WHERE accepted IS NOT NULL").fetchone()["n"] == 2


def test_cabinet_worker_and_login(monkeypatch, tmp_path):
    assert os.environ.get("TEST_DISPOSABLE_DATABASE") == "1"
    staging, password = environment(monkeypatch, tmp_path, "pwa", demo=True)
    with running(staging) as address, sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(permissions=["notifications"])
        master = context.new_page()
        master.goto(address + "/admin")
        expect(master.get_by_role("button", name="Войти")).to_be_visible()
        registration = master.evaluate("""async () => {
            const worker = await navigator.serviceWorker.ready;
            return worker.active.scriptURL;
        }""")
        assert registration == address + "/sw.js"
        with TestClient(app, base_url=address, headers={"origin": address}) as api:
            monkeypatch.setenv("DATABASE_URL", staging["DATABASE_URL"])
            assert public_booking(api).is_success
            with connect() as db:
                visit = db.execute("SELECT id FROM visits").fetchone()["id"]
        path = f"/admin?visit={visit}"
        worker = next(worker for worker in context.service_workers if worker.url == registration)
        body = "Маникюр · 10:00"
        worker.evaluate("""({url, body}) => self.dispatchEvent(new PushEvent('push', {
            data: JSON.stringify({url, body, tag: 'test-visit'})
        }))""", {"url": path, "body": body})
        master.wait_for_function("""async () => {
          const registration = await navigator.serviceWorker.ready;
          return (await registration.getNotifications({tag: 'test-visit'})).length === 1;
        }""")
        destination = worker.evaluate("""async () => {
          const [notice] = await self.registration.getNotifications({tag: 'test-visit'});
          const original = self.clients.openWindow;
          try {
            return await Promise.race([
              new Promise(resolve => {
                self.clients.openWindow = url => {resolve({url, body: notice.body}); return Promise.resolve(null);};
                self.dispatchEvent(new NotificationEvent('notificationclick', {notification: notice}));
              }),
              new Promise(resolve => setTimeout(() => resolve(null), 2500))
            ]);
          } finally {
            self.clients.openWindow = original;
          }
        }""")
        assert destination == {"url": address + path, "body": body}
        master.goto(destination["url"])
        expect(master.get_by_role("button", name="Войти")).to_be_visible()
        master.get_by_label("Пароль").fill(password)
        master.get_by_role("button", name="Войти").click()
        expect(master.locator(f'details[data-id="{visit}"][open]')).to_contain_text("Приёмка push")
        assert master.url == address + path

        safari = browser.new_context(is_mobile=True, viewport={"width": 390, "height": 844},
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1")
        phone = safari.new_page()
        login(phone, address, password)
        phone.get_by_role("link", name="Настройки").click()
        expect(phone.locator("#status")).to_contain_text("На экран Домой")
        expect(phone.get_by_role("button", name="Включить уведомления")).to_be_disabled()
        browser.close()
