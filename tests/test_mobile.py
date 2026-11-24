import os
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright
from storage import initialize


def test_mobile_booking():
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
            page=browser.new_page(viewport=dict(width=390,height=844),is_mobile=True,has_touch=True)
            page.goto(url)
            page.get_by_role("link",name="Записаться",exact=True).click()
            page.get_by_role("button",name="Маникюр",exact=False).click()
            page.locator("#dates button.has-windows").last.click()
            page.locator("#slots button:enabled").first.click()
            page.get_by_label("Соцсеть для связи",exact=False).fill("Telegram @test")
            page.get_by_label("Ваше имя").fill("Проверка браузера")
            page.get_by_label("Телефон").fill("+70000000002")
            def lose_reply(route):
                assert route.fetch().status==200
                route.abort()
            page.route("**/book",lose_reply,times=1)
            submit=page.get_by_role("button",name="Записаться",exact=True)
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
            assert page.get_by_role("button",name="Выйти").count()==0
            page.get_by_role("link",name="График").click()
            assert page.locator(".weekday").count()==7
            weekday=page.locator(".weekday").first
            weekday.locator("[name=closes]").fill("18:30")
            weekday.get_by_role("button",name="Сохранить").click()
            weekday.get_by_text("Сохранено").wait_for()
            page.get_by_text("+ Добавить день",exact=True).click()
            special=page.locator('[data-kind=date]')
            assert not special.locator(".hours").is_visible()
            special.locator("[name=off]").uncheck()
            assert special.locator(".hours").is_visible()
            page.get_by_role("link",name="Настройки").click()
            assert page.get_by_role("button",name="Включить уведомления").is_visible()
            assert not page.locator("#test").is_visible()
            assert page.get_by_role("button",name="Выйти").is_visible()
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
