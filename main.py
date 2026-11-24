import hashlib
import hmac
import json
import os
import re
import secrets
import uuid
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel, Field, AwareDatetime
from psycopg import Error as DatabaseError
from psycopg.errors import ExclusionViolation
from starlette.concurrency import run_in_threadpool

from catalog import (ASSET_PATTERN, PHOTO_LIMIT, PortfolioItem, Profile, Service, database_media, foreground, media_root,
                     photo_variants, save_profile, save_service, save_work, services, store_photo)
from configure import password_hash
from schedule_admin import ScheduleRule, save_rule, visit_options, change_visit
from push import deliver_one, enqueue
from storage import ROOT, connect
from calendar_service import available, timeline, lock, quote, rules, day_hours

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/assets", StaticFiles(directory=ROOT/"static"), name="assets")
pages = Jinja2Templates(directory=ROOT/"templates")
pages.env.globals["foreground"] = foreground


@app.middleware("http")
async def headers(request, call_next):
    if request.method == "POST" and request.url.path != "/jobs/push":
        origin = request.headers.get("origin", "")
        if not origin or urlsplit(origin).netloc != request.headers.get("host") or not origin.startswith(("https://","http://")):
            return JSONResponse({"detail":"Обновите страницу"},403)
    response = await call_next(request)
    response.headers.update({"Cache-Control":"no-store", "Referrer-Policy":"no-referrer",
                             "X-Content-Type-Options":"nosniff","X-Frame-Options":"DENY"})
    return response


@app.exception_handler(RequestValidationError)
async def invalid(request, error):
    if request.url.path.startswith("/admin/content/"):
        labels = {"name": "Имя или бренд", "specialty": "Специализация",
                  "tagline": "Краткое описание", "description": "Полное описание",
                  "phone": "Телефон", "links": "Ссылки", "address": "Адрес",
                  "directions": "Как пройти", "timezone": "Часовой пояс", "accent": "Основной цвет",
                  "background": "Фоновый цвет", "fonts": "Шрифты", "avatar": "Аватар",
                  "cover": "Обложка", "cover_x": "Фокус обложки", "cover_y": "Фокус обложки",
                  "category": "Категория", "title": "Название", "price": "Цена",
                  "minutes": "Длительность", "instructions": "Инструкции перед визитом",
                  "position": "Порядок на витрине", "visible": "Видимость",
                  "addons": "Дополнения", "caption": "Подпись", "service_id": "Услуга",
                  "image": "Фото"}
        location = error.errors()[0]["loc"]
        label = labels.get(location[1]) if len(location) > 1 else None
        detail = f"Проверьте поле «{label}»" if label else "Проверьте данные формы"
        return JSONResponse({"detail": detail}, 422)
    return JSONResponse({"detail":"Проверьте данные формы"},422)


def rate(request, action, maximum):
    ip = request.client.host if request.client else "local"
    key = hmac.digest(os.environ["SESSION_SECRET"].encode(), (action+ip).encode(),"sha256").hex()
    with connect() as db:
        db.execute("DELETE FROM limits WHERE expires<=now()")
        hits = db.execute("""INSERT INTO limits VALUES (%s,1,now()+interval '10 minutes')
          ON CONFLICT(bucket) DO UPDATE SET hits=limits.hits+1 RETURNING hits""",(key,)).fetchone()["hits"]
    if hits > maximum:
        raise HTTPException(429,"Слишком много попыток. Повторите через 10 минут.")


def signer():
    return URLSafeTimedSerializer(os.environ["SESSION_SECRET"],salt="master-login")


def authorized(request):
    try:
        return signer().loads(request.cookies.get("master",""),max_age=43200) == "master"
    except BadSignature:
        return False


def require(request):
    if not authorized(request):
        raise HTTPException(401,"Войдите в кабинет")


def profile_data(db):
    return db.execute("SELECT * FROM profile WHERE id=1").fetchone()


def selected_service(db, service_id):
    service_id = 1 if service_id is None else service_id
    row = db.execute("SELECT * FROM services WHERE visible AND id=%s", (service_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Услуга недоступна")
    return row


@app.get("/healthz")
def health():
    try:
        with connect() as db:
            if not profile_data(db):
                raise HTTPException(503, "База ожидает настройки")
            if database_media():
                db.execute("SELECT key FROM photo_assets LIMIT 0")
    except DatabaseError:
        raise HTTPException(503, "База временно недоступна") from None
    return {"ok": True}


@app.get("/")
@app.get("/admin/new")
def home(request: Request):
    manual = request.url.path.startswith("/admin")
    if manual:
        require(request)
    with connect() as db:
        p = profile_data(db)
        items = services(db, visible=True)
        extras = db.execute("SELECT * FROM addons WHERE visible ORDER BY id").fetchall()
        works = [] if manual else db.execute("SELECT * FROM portfolio WHERE visible ORDER BY position,id").fetchall()
    groups = {}
    for service in items:
        groups.setdefault(service["category"], []).append(service)
    return pages.TemplateResponse(request=request, name="home.html",
        context=dict(p=p, groups=groups, items=items, extras=extras, works=works, manual=manual))


@app.get("/slots")
def slots(addon: int | None = None, service: int | None = None, addons: list[int] = Query(default=[])):
    with connect() as db:
        p = profile_data(db)
        s = quote(db, selected_service(db, service), addon, addons)
        days = timeline(db, p, s["minutes"])
        return dict(times=available(days), days=days, price=s["price"], minutes=s["minutes"], title=s["title"])


class Booking(BaseModel):
    name: str = Field(min_length=1,max_length=80)
    phone: str = Field(max_length=24)
    starts: AwareDatetime
    price: int
    request_id: uuid.UUID
    social: str = Field(default='',max_length=200)
    addon: int|None=None
    service: int | None = None
    addons: list[int] = Field(default_factory=list, max_length=20)
    minutes: int | None = None


@app.post("/book")
@app.post("/admin/book")
def book(request: Request, form: Booking):
    manual=request.url.path.startswith("/admin/")
    if manual:
        require(request)
    phone = re.sub(r"[ ()\-]","",form.phone)
    if not re.fullmatch(r"\+?\d{10,15}",phone) or not form.name.strip():
        raise HTTPException(422,"Проверьте имя и телефон")
    omitted = set()
    if form.service is None:
        omitted.add("service")
    if not form.addons:
        omitted.add("addons")
    if form.minutes is None:
        omitted.add("minutes")
    fingerprint = hashlib.sha256(form.model_dump_json(exclude=omitted).encode()).hexdigest()
    rate(request,"book",40)
    try:
        with connect() as db:
            lock(db)
            old = db.execute("SELECT token,fingerprint FROM visits WHERE request_id=%s",(form.request_id,)).fetchone()
            if old:
                if old["fingerprint"] != fingerprint:
                    raise HTTPException(409,"Условия изменены. Выберите время заново.")
                return {"url":"/v/"+old["token"]}
            p = profile_data(db)
            s = quote(db, selected_service(db, form.service), form.addon, form.addons)
            if s["price"] != form.price:
                raise HTTPException(409,"Цена изменилась. Проверьте сумму и подтвердите снова.")
            if form.minutes is not None and form.minutes != s["minutes"]:
                raise HTTPException(409,"Длительность изменилась. Проверьте время и подтвердите снова.")
            if form.starts.isoformat() not in available(timeline(db,p,s["minutes"])):
                raise HTTPException(409,"Это время уже недоступно. Выберите другое окно.")
            token, visit = secrets.token_urlsafe(32), uuid.uuid4()
            db.execute("""INSERT INTO visits(id,request_id,fingerprint,token,name,phone,title,price,minutes,starts,ends,instructions,social)
                          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                       (visit,form.request_id,fingerprint,token,form.name.strip(),phone,s["title"],s["price"],
                        s["minutes"],form.starts,form.starts+timedelta(minutes=s["minutes"]),s["instructions"],form.social.strip()))
            local = form.starts.astimezone(ZoneInfo(p["timezone"]))
            if not manual:
                enqueue(db,f"{s['title']} · {local:%d.%m %H:%M}",visit)
    except ExclusionViolation:
        raise HTTPException(409,"Время занято. Выберите другое окно.")
    return {"url":"/v/"+token}


@app.get("/v/{token}")
def card(request: Request,token: str):
    with connect() as db:
        v = db.execute("SELECT title,price,starts,ends,instructions,cancelled FROM visits WHERE token=%s",(token,)).fetchone()
        if not v:
            raise HTTPException(404,"Запись не найдена")
        p = profile_data(db)
    return pages.TemplateResponse(request=request,name="visit.html",context=dict(v=v,p=p,z=ZoneInfo(p["timezone"])))


@app.get("/admin")
def admin(request: Request,visit: uuid.UUID|None=None, day: date|None=None, tab: str="visits"):
    if not authorized(request):
        return pages.TemplateResponse(request=request,name="login.html",context={})
    with connect() as db:
        p = profile_data(db)
        z=ZoneInfo(p["timezone"])
        selected = db.execute("SELECT * FROM visits WHERE id=%s",(visit,)).fetchone() if visit else None
        day = selected["starts"].astimezone(z).date() if selected else day or datetime.now(z).date()
        rows=db.execute("SELECT * FROM visits WHERE (starts AT TIME ZONE %s)::date=%s ORDER BY starts",
                        (p["timezone"],day)).fetchall()
        pauses=db.execute("SELECT * FROM breaks WHERE (starts AT TIME ZONE %s)::date=%s ORDER BY starts",(p["timezone"],day)).fetchall()
        weekly, exceptions=rules(db)
        today=datetime.now(z).date()
        quick=[today+timedelta(days=i) for i in range(3)]
        week=[today+timedelta(days=i-today.weekday()) for i in range(7)]
        if tab not in {"visits","schedule","settings"} or visit:
            tab="visits"
    return pages.TemplateResponse(request=request,name="admin.html",context=dict(rows=rows,day=day,z=z,pauses=pauses,weekly=weekly,exceptions=exceptions,quick=quick,week=week,tab=tab,p=p,
        visit=visit,public_key=os.environ["VAPID_PUBLIC"]))


@app.get("/admin/content")
def content(request: Request):
    if not authorized(request):
        return RedirectResponse("/admin")
    with connect() as db:
        profile = profile_data(db)
        items = services(db)
        addons = db.execute("SELECT * FROM addons ORDER BY id").fetchall()
        works = db.execute("SELECT * FROM portfolio ORDER BY position,id").fetchall()
    return pages.TemplateResponse(request=request, name="content.html",
        context=dict(p=profile, items=items, addons=addons, works=works))


@app.post("/admin/content/profile")
def update_profile(request: Request, form: Profile):
    require(request)
    with connect() as db:
        lock(db)
        try:
            save_profile(db, form)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
    return {"ok": True}


@app.post("/admin/content/service")
def update_service(request: Request, form: Service):
    require(request)
    with connect() as db:
        lock(db)
        try:
            return {"id": save_service(db, form)}
        except ValueError as error:
            raise HTTPException(422, str(error)) from None


@app.post("/admin/content/work")
@app.post("/admin/content/work/{item_id}")
def update_work(request: Request, form: PortfolioItem, item_id: int | None = None):
    require(request)
    with connect() as db:
        lock(db)
        try:
            return {"id": save_work(db, form, item_id)}
        except ValueError as error:
            raise HTTPException(422, str(error)) from None


@app.post("/admin/content/photo")
async def upload_photo(request: Request):
    require(request)
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > PHOTO_LIMIT:
            raise HTTPException(413, "Размер фото должен быть не больше 8 МБ")
        raw.extend(chunk)
    try:
        key, variants = await run_in_threadpool(photo_variants, raw)
        await run_in_threadpool(store_photo, key, variants)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    return {"image": key}


@app.get("/media/{key}/{size}")
@app.get("/admin/content/media/{key}/{size}")
def photo(request: Request, key: str, size: str):
    if not re.fullmatch(ASSET_PATTERN, key) or size not in {"full", "thumb"}:
        raise HTTPException(404)
    admin_photo = request.url.path.startswith("/admin/")
    if admin_photo:
        require(request)
    if database_media() or not admin_photo:
        with connect() as db:
            if not admin_photo:
                visible = db.execute("""SELECT 1 FROM profile WHERE avatar=%s OR cover=%s
                    UNION ALL SELECT 1 FROM portfolio WHERE visible AND image=%s LIMIT 1""",
                    (key, key, key)).fetchone()
                if not visible:
                    raise HTTPException(404)
            if database_media():
                column = "full_data" if size == "full" else "thumb_data"
                row = db.execute(f"SELECT {column} FROM photo_assets WHERE key=%s", (key,)).fetchone()
                if not row:
                    raise HTTPException(404)
                return Response(row[column], media_type="image/webp")
    path = media_root() / f"{key}-{size}.webp"
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/webp")


@app.post("/admin/rules")
def schedule(request: Request, form: ScheduleRule):
    require(request)
    save_rule(form)
    return {"ok":True}


@app.get("/admin/options/{visit}")
def options(request: Request,visit: uuid.UUID):
    require(request)
    with connect() as db:
        return visit_options(db,visit)


class Move(BaseModel):
    starts: AwareDatetime


@app.post("/admin/move/{visit}")
def move(request: Request,visit: uuid.UUID,form: Move):
    require(request)
    change_visit(visit,form.starts)
    return {"ok":True}


@app.post("/admin/cancel/{visit}")
def cancel(request: Request,visit: uuid.UUID):
    require(request)
    change_visit(visit,None)
    return {"ok":True}


@app.post("/admin/unblock/{pause}")
def unblock(request: Request,pause: uuid.UUID):
    require(request)
    with connect() as db:
        lock(db)
        db.execute("DELETE FROM breaks WHERE id=%s",(pause,))
    return {"ok":True}


class Login(BaseModel):
    password: str = Field(max_length=512)


@app.post("/admin/login")
def login(request: Request, form: Login):
    rate(request,"login",10)
    salt, correct = os.environ["ADMIN_HASH"].split(".")
    if not hmac.compare_digest(password_hash(form.password,salt),correct):
        raise HTTPException(403,"Неверный пароль")
    response=JSONResponse({"ok":True})
    response.set_cookie("master",signer().dumps("master"),httponly=True,secure=True,
                        samesite="strict",max_age=43200,path="/admin")
    return response


@app.post("/admin/logout")
def logout(request: Request):
    require(request)
    response=RedirectResponse("/admin",303)
    response.delete_cookie("master",path="/admin")
    return response


class Device(BaseModel):
    endpoint: str = Field(max_length=2048)
    keys: dict[str,str] = {}


@app.post("/admin/device/{action}")
def device(request: Request,action: str,form: Device):
    require(request)
    host=urlsplit(form.endpoint)
    if (host.scheme!="https" or not host.hostname or host.netloc!=host.hostname or
        not (host.hostname in {"fcm.googleapis.com","web.push.apple.com","updates.push.services.mozilla.com"}
             or host.hostname.endswith(".push.apple.com"))):
        raise HTTPException(422,"Неизвестный сервис push")
    with connect() as db:
        if action=="enable":
            if not all(re.fullmatch(r"[A-Za-z0-9_-]{16,128}",form.keys.get(k,"")) for k in ("auth","p256dh")):
                raise HTTPException(422,"Некорректная подписка устройства")
            db.execute("""INSERT INTO subscriptions VALUES(%s,%s::jsonb) ON CONFLICT(endpoint)
              DO UPDATE SET info=excluded.info""",(form.endpoint,form.model_dump_json()))
        elif action=="disable":
            db.execute("DELETE FROM subscriptions WHERE endpoint=%s",(form.endpoint,))
        elif action in {"test","status"}:
            exists=db.execute("SELECT 1 FROM subscriptions WHERE endpoint=%s",(form.endpoint,)).fetchone()
            if action=="status":
                return {"enabled":bool(exists)}
            if not exists:
                raise HTTPException(409,"Подключите устройство заново")
            enqueue(db,"Проверка уведомлений",endpoint=form.endpoint)
        else:
            raise HTTPException(404)
    return {"ok":True}


@app.post("/jobs/push")
def drain(request: Request):
    if not hmac.compare_digest(request.headers.get("authorization",""),"Bearer "+os.environ["CRON_SECRET"]):
        raise HTTPException(403)
    return {"processed":sum(1 for _ in range(4) if deliver_one())}


@app.get("/sw.js")
def sw():
    return FileResponse(ROOT/"static"/"sw.js",media_type="text/javascript")
