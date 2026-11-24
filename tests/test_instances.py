import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from contextlib import ExitStack, contextmanager
from io import BytesIO
from pathlib import Path
from urllib.request import urlopen

import psycopg
import pytest
from PIL import Image
from playwright.sync_api import expect, sync_playwright
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

import push
from catalog import PortfolioItem, Profile, photo_variants, save_profile, save_work, store_photo
from configure import settings
from starter import import_starter
from storage import ROOT, connect, initialize

KIT = ROOT / "starter-kit/profile.json"


def picture(color):
    target = BytesIO()
    Image.new("RGB", (800, 600), color).save(target, "WEBP")
    return target.getvalue()


def environment(monkeypatch, tmp_path, label, demo):
    base = os.environ["DATABASE_URL"]
    database = "stage3_" + label + "_" + uuid.uuid4().hex
    with psycopg.connect(base, autocommit=True) as db:
        db.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    password = uuid.uuid4().hex
    values = settings(password, "test@example.org") | {
        "DATABASE_URL": make_conninfo(base, dbname=database),
        "MEDIA_DIR": str(tmp_path / label),
    }
    with monkeypatch.context() as env:
        for key, value in values.items():
            env.setenv(key, value)
        initialize(demo=demo)
    return {**os.environ, **values}, password


@contextmanager
def running(env):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    address = f"http://127.0.0.1:{port}"
    with subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app",
                           "--port", str(port), "--no-access-log"], env=env) as server:
        try:
            for _ in range(80):
                try:
                    with urlopen(address, timeout=1) as response:
                        assert response.status == 200
                    break
                except OSError:
                    if server.poll() is not None:
                        pytest.fail("Веб-процесс завершился при запуске")
                    time.sleep(.1)
            else:
                pytest.fail("Локальный экземпляр не запустился")
            yield address
        finally:
            server.terminate()
            server.wait(timeout=10)


def login(page, address, password):
    page.goto(address + "/admin")
    page.get_by_label("Пароль").fill(password)
    page.get_by_role("button", name="Войти").click()
    page.get_by_role("heading", name="Записи").wait_for()


def test_starter_validation_is_atomic(monkeypatch, tmp_path):
    assert os.environ.get("TEST_DISPOSABLE_DATABASE") == "1"
    env, _ = environment(monkeypatch, tmp_path, "invalid", demo=False)
    monkeypatch.setenv("DATABASE_URL", env["DATABASE_URL"])
    monkeypatch.setenv("MEDIA_DIR", env["MEDIA_DIR"])
    broken = json.loads(KIT.read_text(encoding="utf-8"))
    broken["profile"]["cover"] = ""
    broken["portfolio"][0]["image"] = "photos/missing.webp"
    config = tmp_path / "bad.json"
    config.write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(ValueError, match=r"portfolio\[1\].image"):
        import_starter(config)
    with connect() as db:
        assert db.execute("SELECT NOT configured AS empty FROM profile").fetchone()["empty"]
        assert not db.execute("SELECT id FROM services").fetchone()
    assert not Path(env["MEDIA_DIR"]).exists()
    import_starter(KIT)
    with pytest.raises(ValueError, match="пустого экземпляра"):
        import_starter(KIT)
    initialize()
    with connect() as db:
        assert db.execute("SELECT count(*) AS total FROM services").fetchone()["total"] == 2


def test_two_instances(monkeypatch, tmp_path, record_property):
    assert os.environ.get("TEST_DISPOSABLE_DATABASE") == "1"
    first, first_password = environment(monkeypatch, tmp_path, "nails", demo=True)
    with monkeypatch.context() as env:
        env.setenv("DATABASE_URL", first["DATABASE_URL"])
        env.setenv("MEDIA_DIR", first["MEDIA_DIR"])
        first_cover, variants = photo_variants(picture("pink"))
        store_photo(first_cover, variants)
        with connect() as db:
            profile = db.execute("SELECT * FROM profile").fetchone()
            values = {key: profile[key] for key in Profile.model_fields}
            values.update(cover=first_cover, links=[{"title": "Страница Лины", "url": "https://example.org/nails"}])
            save_profile(db, Profile.model_validate(values))
            save_work(db, PortfolioItem(image=first_cover, caption="Маникюр Лины", service_id=1))
    started = time.monotonic()
    second, second_password = environment(monkeypatch, tmp_path, "lashes", demo=False)
    with monkeypatch.context() as env:
        env.setenv("DATABASE_URL", second["DATABASE_URL"])
        env.setenv("MEDIA_DIR", second["MEDIA_DIR"])
        import_starter(KIT)
    preparation_seconds = time.monotonic() - started
    with ExitStack() as stack:
        nails = stack.enter_context(running(first))
        started = time.monotonic()
        lashes = stack.enter_context(running(second))
        record_property("second_instance_seconds", round(preparation_seconds + time.monotonic() - started, 2))
        playwright = stack.enter_context(sync_playwright())
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        master = context.new_page()
        first_site = context.new_page()
        second_site = context.new_page()

        login(master, nails, first_password)
        first_api = master.request
        nails_endpoint = "https://fcm.googleapis.com/demo-nails"
        lashes_endpoint = "https://fcm.googleapis.com/demo-lashes"
        keys = {"auth": "a" * 22, "p256dh": "b" * 87}
        assert first_api.post(nails + "/admin/device/enable", headers={"Origin": nails},
                             data={"endpoint": nails_endpoint, "keys": keys}).ok

        login(master, lashes, second_password)
        api = master.request
        assert api.post(lashes + "/admin/device/enable", headers={"Origin": lashes},
                        data={"endpoint": lashes_endpoint, "keys": keys}).ok
        # Порт не разделяет cookie. Первый кабинет принимает только собственную подпись.
        assert api.post(nails + "/admin/device/enable", headers={"Origin": nails},
                        data={"endpoint": lashes_endpoint, "keys": keys}).status == 401
        master.get_by_role("link", name="Настройки").click()
        master.get_by_role("link", name="Профиль, услуги и портфолио").click()
        master.get_by_label("Имя или бренд").fill("Студия Ивы · ресницы")
        master.locator("#preview").get_by_role("heading", name="Студия Ивы · ресницы").wait_for()
        master.get_by_role("button", name="Сохранить профиль").click()
        master.locator("#profile").get_by_text("Сохранено").wait_for()
        assert master.evaluate("document.documentElement.scrollWidth <= innerWidth")

        first_site.goto(nails)
        second_site.goto(lashes)
        first_site.get_by_role("heading", name="Студия Лины").wait_for()
        second_site.get_by_role("heading", name="Студия Ивы · ресницы").wait_for()
        assert first_site.locator(".profile-page").get_attribute("data-fonts") == "classic"
        assert first_site.get_by_role("link", name="Страница Лины").get_attribute("href") == "https://example.org/nails"
        original_nails_cover = first_site.locator(".profile-cover").get_attribute("src")
        assert api.get(nails + original_nails_cover).ok and api.get(lashes + original_nails_cover).status == 404
        assert second_site.locator(".profile-page").get_attribute("data-fonts") == "modern"
        assert second_site.get_by_role("link", name="Страница студии").get_attribute("href") == "https://example.org/iva-studio"
        assert first_site.locator("#services").get_by_role("button", name="Маникюр").count() == 1
        assert second_site.get_by_role("button", name="Ламинирование").count() == 1
        assert first_site.locator("figcaption").inner_text() == "Маникюр Лины"
        assert second_site.locator("figcaption").inner_text() == "Классика с натуральным изгибом"
        background = "(node) => getComputedStyle(node).backgroundColor"
        assert first_site.locator(".profile-page").evaluate(background) == "rgb(252, 248, 245)"
        assert second_site.locator(".profile-page").evaluate(background) == "rgb(240, 237, 247)"
        initial_cover = second_site.locator(".profile-cover").get_attribute("src")
        assert api.get(lashes + initial_cover).ok and api.get(nails + initial_cover).status == 404
        assert api.get(nails + "/slots").json()["price"] == 2000
        quote = api.get(lashes + "/slots?service=1&addons=1&addons=2").json()
        assert quote["times"] and (quote["price"], quote["minutes"]) == (3200, 130)

        master.get_by_label("Обложка", exact=True).set_input_files({
            "name": "cover.webp", "mimeType": "image/webp", "buffer": picture("purple")})
        master.locator('[data-picture="cover"]').get_by_text("Фото готово.", exact=False).wait_for()
        old_positions = master.locator("#preview .profile-cover").evaluate("(img) => img.style.objectPosition")
        master.locator("[name=cover_y]").press("ArrowLeft")
        assert master.locator("#preview .profile-cover").evaluate("(img) => img.style.objectPosition") != old_positions
        master.get_by_role("button", name="Сохранить профиль").click()
        master.locator("#profile").get_by_text("Сохранено").wait_for()

        editor = master.locator("#service-1")
        editor.locator("summary").click()
        editor.locator('input[name=price]').fill("2900")
        editor.get_by_role("button", name="Сохранить услугу").click()
        master.locator("#service-1").get_by_text("Сохранено").wait_for()
        assert api.get(nails + "/slots").json()["price"] == 2000
        updated = api.get(lashes + "/slots?service=1").json()
        assert updated["price"] == 2900
        stale = api.post(lashes + "/book", headers={"Origin": lashes},
            data={"service": 1, "minutes": 10, "price": 2900, "starts": updated["times"][0],
                  "request_id": str(uuid.uuid4()), "name": "Тест", "phone": "+70000000004"})
        assert stale.status == 409 and "Длительность изменилась" in stale.json()["detail"]
        first_site.reload()
        second_site.reload()
        assert first_site.locator(".profile-cover").get_attribute("src") == original_nails_cover
        assert second_site.locator(".profile-cover").get_attribute("src") != initial_cover

        work = master.locator("#work-list details").first
        work.locator("summary").click()
        work.get_by_label("Заменить фото").set_input_files({
            "name": "work.webp", "mimeType": "image/webp", "buffer": picture("teal")})
        work.get_by_text("Фото готово.", exact=False).wait_for()
        work.get_by_role("button", name="Сохранить работу").click()
        work.get_by_text("Сохранено").wait_for()
        second_site.reload()
        thumbnail = second_site.locator(".work-open img").get_attribute("src")
        assert thumbnail.endswith("/thumb") and api.get(lashes + thumbnail).ok
        second_site.get_by_role("button", name="Открыть фото").click()
        assert second_site.locator("#work-large").get_attribute("src") == thumbnail.replace("/thumb", "/full")
        with Image.open(BytesIO(api.get(lashes + thumbnail).body())) as thumb:
            assert thumb.width == 420
        with Image.open(BytesIO(api.get(lashes + thumbnail.replace("/thumb", "/full")).body())) as large:
            assert large.width == 800
        second_site.get_by_role("button", name="Закрыть").click()
        assert second_site.locator(".work-open").evaluate("(button) => document.activeElement === button")
        second_site.get_by_role("button", name="Открыть фото").click()
        second_site.get_by_role("button", name="Записаться на эту услугу").click()
        second_site.locator("#slots button:enabled").first.wait_for()
        expect(second_site.locator("#summary")).to_contain_text("2900 ₽")
        second_site.get_by_label("Ваше имя").fill("Проверка изоляции")
        second_site.get_by_label("Телефон").fill("+70000000003")
        second_site.get_by_role("button", name="Записаться", exact=True).click()
        second_site.get_by_role("heading", name="Вы записаны").wait_for()
        with monkeypatch.context() as env:
            env.setenv("DATABASE_URL", second["DATABASE_URL"])
            with connect() as db:
                visit = db.execute("SELECT id FROM visits").fetchone()["id"]
        master.goto(lashes + "/admin?visit=" + str(visit))
        assert "Проверка изоляции" in master.locator(".cabinet").text_content()
        token_path = second_site.url.removeprefix(lashes)
        assert api.get(nails + token_path).status == 404

        sent = []
        monkeypatch.setattr(push, "webpush", lambda info, data, **kwargs: sent.append((info["endpoint"], data)))
        with monkeypatch.context() as env:
            env.setenv("DATABASE_URL", first["DATABASE_URL"])
            assert not push.deliver_one()
            with connect() as db:
                assert not db.execute("SELECT id FROM visits").fetchone()
            env.setenv("DATABASE_URL", second["DATABASE_URL"])
            assert push.deliver_one() and not push.deliver_one()
        assert len(sent) == 1 and sent[0][0] == lashes_endpoint
        notification = json.loads(sent[0][1])
        assert "Классическое наращивание" in notification["body"]
        assert notification["url"] == "/admin?visit=" + str(visit)
        master.goto(lashes + "/admin/content#portfolio-editor")
        master.get_by_label("Добавить фото").set_input_files([
            {"name": "first.webp", "mimeType": "image/webp", "buffer": picture("pink")},
            {"name": "broken.webp", "mimeType": "image/webp", "buffer": b"not an image"},
            {"name": "last.webp", "mimeType": "image/webp", "buffer": picture("orange")},
        ])
        master.get_by_role("button", name="Загрузить фото").click()
        master.get_by_text("last.webp · загружено").wait_for()
        assert master.get_by_text("broken.webp · Нужна фотография", exact=False).is_visible()
        assert master.locator("#work-list details").count() == 3
        browser.close()

    original = Path(os.environ["TEST_POSTGRES_DATA"])
    runtime = Path(os.environ["TEST_POSTGRES_BIN"])
    restored_data = tmp_path / "restored-data"
    photos = tmp_path / "photos"
    source_port = conninfo_to_dict(second["DATABASE_URL"])["port"]
    control = runtime / "pg_ctl.exe"

    def start(data, port):
        subprocess.run([control, "-D", data, "-l", data.parent / (data.name + ".log"),
                        "-o", f"-h 127.0.0.1 -p {port}", "-w", "start"], check=True)

    def stop(data):
        subprocess.run([control, "-D", data, "-m", "fast", "-w", "stop"], check=True)

    photo_archive = shutil.make_archive(str(tmp_path / "photos"), "tar", second["MEDIA_DIR"])
    stop(original)
    try:
        db_archive = shutil.make_archive(str(tmp_path / "database"), "tar", original)
    finally:
        start(original, source_port)
    shutil.unpack_archive(db_archive, restored_data, filter="data")
    shutil.unpack_archive(photo_archive, photos, filter="data")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    restored_env = {**second, "DATABASE_URL": make_conninfo(second["DATABASE_URL"], port=port),
                    "MEDIA_DIR": str(photos)}
    start(restored_data, port)
    try:
        with running(restored_env) as address:
            for route in ("/", token_path, thumbnail, thumbnail.replace("/thumb", "/full")):
                with urlopen(address + route, timeout=2) as response:
                    assert response.status == 200
            with urlopen(address + token_path, timeout=2) as response:
                assert "2900 ₽" in response.read().decode()
    finally:
        stop(restored_data)
