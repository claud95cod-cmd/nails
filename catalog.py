import os
import re
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PIL import Image, ImageOps, UnidentifiedImageError
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from storage import ROOT, connect

PHOTO_LIMIT = 8 * 1024 * 1024
ASSET_PATTERN = r"[0-9a-f]{64}"
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Color = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]
Asset = Annotated[str, StringConstraints(pattern=rf"^(?:{ASSET_PATTERN})?$")]
Position = Annotated[int, Field(ge=0, le=9999)]
Price = Annotated[int, Field(ge=0, le=1000000)]
ItemId = Annotated[int, Field(ge=1, le=2147483647)]


class Form(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Link(Form):
    title: Name
    url: str = Field(max_length=400)

    @field_validator("url")
    @classmethod
    def https_link(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Укажите ссылку HTTPS")
        return value


class Profile(Form):
    name: Name
    specialty: str = Field(max_length=100)
    tagline: str = Field(max_length=200)
    description: str = Field(max_length=2000)
    phone: str = Field(max_length=24)
    links: list[Link] = Field(max_length=8)
    address: str = Field(max_length=250)
    directions: str = Field(max_length=800)
    timezone: Name
    accent: Color
    background: Color
    fonts: Literal["classic", "modern"]
    avatar: Asset = ""
    cover: Asset = ""
    cover_x: int = Field(default=50, ge=0, le=100)
    cover_y: int = Field(default=50, ge=0, le=100)

    @field_validator("timezone")
    @classmethod
    def known_zone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Укажите часовой пояс, например Europe/Astrakhan") from None
        return value

    @field_validator("phone")
    @classmethod
    def phone_number(cls, value):
        if value and not re.fullmatch(r"\+?\d{10,15}", re.sub(r"[ ()-]", "", value)):
            raise ValueError("Введите телефон с кодом страны")
        return value


class Addon(Form):
    id: ItemId | None = None
    title: Name
    price: Price
    minutes: int = Field(ge=0, le=480)
    visible: bool = True


class Service(Form):
    id: ItemId | None = None
    category: Name
    title: Name
    price: Price
    minutes: int = Field(ge=5, le=720)
    instructions: str = Field(default="", max_length=1500)
    position: Position = 0
    visible: bool = True
    addons: list[Addon] = Field(default_factory=list, max_length=20)


class PortfolioItem(Form):
    image: Annotated[str, StringConstraints(pattern=rf"^{ASSET_PATTERN}$")]
    caption: str = Field(default="", max_length=250)
    position: Position = 0
    service_id: ItemId | None = None
    visible: bool = True


def database_media():
    return os.getenv("MEDIA_STORAGE") == "postgres"


def media_root():
    return Path(os.environ.get("MEDIA_DIR", ROOT / "media"))


def photo_variants(raw):
    if not raw or len(raw) > PHOTO_LIMIT:
        raise ValueError("Размер фото должен быть не больше 8 МБ")
    try:
        with Image.open(BytesIO(raw), formats=["JPEG", "PNG", "WEBP"]) as source:
            if source.width * source.height > 24_000_000 or getattr(source, "is_animated", False):
                raise ValueError("Загрузите обычное фото до 24 мегапикселей")
            mode = "RGBA" if source.has_transparency_data else "RGB"
            image = ImageOps.exif_transpose(source).convert(mode)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError):
        raise ValueError("Нужна фотография JPEG, PNG или WebP") from None
    variants = []
    for size in (1600, 420):
        sized = image.copy()
        sized.thumbnail((size, size), Image.Resampling.LANCZOS)
        output = BytesIO()
        sized.save(output, "WEBP", quality=85)
        variants.append(output.getvalue())
    return sha256(variants[0]).hexdigest(), variants


def photo_paths(key):
    return tuple(media_root() / f"{key}-{size}.webp" for size in ("full", "thumb"))


def store_photo(key, variants, db=None):
    if database_media():
        query = """INSERT INTO photo_assets(key,full_data,thumb_data)
            VALUES (%s,%s,%s) ON CONFLICT(key) DO NOTHING"""
        if db is not None:
            db.execute(query, (key, *variants))
        else:
            with connect() as connection:
                connection.execute(query, (key, *variants))
        return

    media_root().mkdir(parents=True, exist_ok=True)
    for path, content in zip(photo_paths(key), variants):
        if path.is_file():
            continue
        with NamedTemporaryFile(dir=path.parent, delete=False) as temp:
            temp.write(content)
        try:
            os.replace(temp.name, path)
        finally:
            Path(temp.name).unlink(missing_ok=True)


def require_photo(db, key):
    if not key:
        return
    if database_media():
        exists = db.execute("SELECT 1 FROM photo_assets WHERE key=%s", (key,)).fetchone()
    else:
        exists = all(path.is_file() for path in photo_paths(key))
    if not exists:
        raise ValueError("Загрузите фото заново")


def save_profile(db, form):
    require_photo(db, form.avatar)
    require_photo(db, form.cover)
    values = form.model_dump()
    values["links"] = Jsonb(values["links"])
    db.execute("""UPDATE profile SET name=%(name)s, specialty=%(specialty)s, tagline=%(tagline)s,
        description=%(description)s, phone=%(phone)s, links=%(links)s, address=%(address)s,
        directions=%(directions)s, timezone=%(timezone)s, accent=%(accent)s, background=%(background)s,
        fonts=%(fonts)s, avatar=%(avatar)s, cover=%(cover)s, cover_x=%(cover_x)s, cover_y=%(cover_y)s,
        configured=true WHERE id=1""", values)


def services(db, visible=False):
    return db.execute("""SELECT * FROM services WHERE visible OR NOT %s
        ORDER BY position,id""", (visible,)).fetchall()


def save_service(db, form):
    fields = (form.title, form.price, form.minutes, form.instructions, form.category,
              form.position, form.visible)
    service_id = form.id
    if service_id is None:
        service_id = db.execute("""INSERT INTO services(id,title,price,minutes,instructions,category,position,visible)
            VALUES ((SELECT COALESCE(MAX(id),0)+1 FROM services),%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            fields).fetchone()["id"]
    elif not db.execute("""UPDATE services SET title=%s,price=%s,minutes=%s,instructions=%s,
            category=%s,position=%s,visible=%s WHERE id=%s""", (*fields, service_id)).rowcount:
        raise ValueError("Услуга не найдена")

    seen = set()
    for addon in form.addons:
        addon_fields = (addon.title, addon.price, addon.minutes, addon.visible)
        if addon.id is None:
            db.execute("""INSERT INTO addons(id,service_id,title,price,minutes,visible)
                VALUES ((SELECT COALESCE(MAX(id),0)+1 FROM addons),%s,%s,%s,%s,%s)""",
                (service_id, *addon_fields))
            continue
        if addon.id in seen or not db.execute("""UPDATE addons SET title=%s,price=%s,minutes=%s,
                visible=%s WHERE service_id=%s AND id=%s""",
                (*addon_fields, service_id, addon.id)).rowcount:
            raise ValueError("Проверьте дополнения к услуге")
        seen.add(addon.id)
    return service_id


def save_work(db, work, item_id=None):
    require_photo(db, work.image)
    if work.service_id and not db.execute("SELECT id FROM services WHERE id=%s", (work.service_id,)).fetchone():
        raise ValueError("Выберите существующую услугу")
    values = (work.image, work.caption, work.position, work.service_id, work.visible)
    if item_id is None:
        return db.execute("""INSERT INTO portfolio(image,caption,position,service_id,visible)
            VALUES (%s,%s,%s,%s,%s) RETURNING id""", values).fetchone()["id"]
    if not db.execute("""UPDATE portfolio SET image=%s,caption=%s,position=%s,service_id=%s,
            visible=%s WHERE id=%s""", (*values, item_id)).rowcount:
        raise ValueError("Работа не найдена")
    return item_id


def foreground(color):
    channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = (channel / 12.92 if channel <= 0.04045 else
              ((channel + 0.055) / 1.055) ** 2.4 for channel in channels)
    luminance = sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    return "#000000" if luminance > 0.179 else "#ffffff"
