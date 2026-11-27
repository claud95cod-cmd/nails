import os
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright
from storage import initialize


def test_mobile_booking(tmp_path):
    assert os.environ.get("TEST_DISPOSABLE_DATABASE")=="1"
    initialize()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0))
        port=sock.getsockname()[1]
    url=f"http://127.0.0.1:{port}"
    server=subprocess.Popen([sys.executable,"-m","uvicorn","main:app","--port",str(port),"--no-access-log"])
    try:
        for _ in range(60):
            try:
                with urlopen(url,timeout=1):break
            except OSError: time.sleep(.2)
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(channel="chrome",headless=True)
            desktop = browser.new_page(viewport=dict(width=1440, height=900))
            desktop.goto(url)
            assert desktop.evaluate("document.fonts.load('16px Manrope').then(fonts => fonts.length === 1)")
            desktop.screenshot(path=tmp_path / "storefront-desktop.png")
            desktop.get_by_role("button", name="Открыть календарь").click()
            panel = desktop.get_by_role("dialog")
            panel.get_by_text("Шаг 1 из 3").wait_for()
            panel.locator("#slots button:enabled").first.wait_for()
            desktop.screenshot(path=tmp_path / "booking-desktop.png")
            panel.locator("#slots button:enabled").first.click()
            panel.get_by_role("button", name="Далее").click()
            panel.get_by_text("Шаг 2 из 3").wait_for()
            panel.get_by_role("button", name="Маникюр", exact=False).click()
            panel.get_by_role("button", name="Далее").click()
            panel.get_by_text("Шаг 3 из 3").wait_for()
            panel.get_by_label("Ваше имя").fill("Проверка на ПК")
            panel.get_by_role("button", name="Назад").click()
            panel.get_by_role("button", name="Далее").click()
            assert panel.get_by_label("Ваше имя").input_value() == "Проверка на ПК"
            panel.get_by_role("button", name="Закрыть").click()
            desktop.locator("[data-start]").first.click()
            panel.get_by_text("Шаг 2 из 3").wait_for()
            desktop.close()
            page=browser.new_page(viewport=dict(width=390,height=844),is_mobile=True,has_touch=True)
            page.goto(url)
            page.screenshot(path=tmp_path / "storefront-mobile.png")
            page.get_by_role("link",name="Выбрать услугу",exact=True).click()
            page.get_by_role("dialog").get_by_role("button",name="Маникюр",exact=False).click()
            page.get_by_role("button", name="Далее").click()
            page.locator("#dates button.has-windows").last.click()
            page.locator("#slots button:enabled").first.click()
            page.get_by_role("button", name="Далее").click()
            page.get_by_label("Соцсеть для связи",exact=False).fill("Telegram @test")
            page.get_by_label("Ваше имя").fill("Проверка браузера")
            page.get_by_label("Телефон").fill("+70000000002")
            page.screenshot(path=tmp_path / "booking-mobile.png")
            def lose_reply(route):
                assert route.fetch().status==200
                route.abort()
            page.route("**/book",lose_reply,times=1)
            submit=page.get_by_role("button",name="Записаться",exact=True)
            assert submit.is_disabled()
            page.locator("#consent").check()
            submit.click()
            page.get_by_text("Ответ не получен.",exact=False).wait_for()
            assert page.get_by_label("Телефон").input_value()=="+70000000002"
            submit.click()
            page.get_by_role("heading",name="Вы записаны").wait_for()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.reload()
            assert page.get_by_role("heading",name="Вы записаны").is_visible()
            page.goto(url+"/admin")
            page.get_by_label("Пароль").fill(os.environ["TEST_MASTER_PASSWORD"])
            page.get_by_role("button",name="Войти").click()
            page.get_by_role("heading",name="Записи").wait_for()
            menu = page.get_by_role("navigation", name="Кабинет мастера")
            assert menu.get_by_role("link").count() == 4
            menu.get_by_role("link", name="Витрина").click()
            page.get_by_role("heading", name="Витрина", exact=True).wait_for()
            assert menu.locator("[aria-current=page]").inner_text() == "Витрина"
            menu.get_by_role("link", name="Записи").click()
            page.get_by_role("link", name="Добавить визит", exact=False).click()
            page.get_by_role("heading", name="Добавить визит").wait_for()
            menu.get_by_role("link", name="Записи").click()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=tmp_path / "master-mobile.png")
            assert page.get_by_role("button",name="Выйти").count()==0
            page.get_by_role("link",name="График").click()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.get_by_role("link",name="Неделя",exact=True).click()
            assert page.locator(".week-row").count()==7
            page.get_by_label("Пн · конец").fill("18:30")
            page.get_by_role("button",name="Применить ко всем").click()
            assert page.get_by_label("Вс · конец").input_value()=="18:30"
            page.get_by_role("button",name="Сохранить изменения").click()
            page.get_by_text("Сохранено",exact=True).wait_for()
            page.get_by_label("Пн · конец").fill("18:00")
            page.get_by_role("button",name="Применить ко всем").click()
            page.get_by_role("button",name="Сохранить изменения").click()
            page.wait_for_load_state("networkidle")
            page.get_by_role("link",name="Календарь",exact=True).click()
            page.get_by_text("Своё время",exact=True).click()
            assert page.locator(".custom-hours").is_visible()
            page.get_by_text("Выходной",exact=True).last.click()
            assert not page.locator(".custom-hours").is_visible()
            page.get_by_role("button",name="+ Добавить перерыв").click()
            assert page.locator("#break-list [name=opens]").last.input_value()=="13:00"
            page.get_by_role("link",name="Настройки").click()
            assert page.get_by_role("button",name="Включить уведомления").is_visible()
            assert not page.locator("#test").is_visible()
            assert page.get_by_role("button",name="Выйти").is_visible()
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
