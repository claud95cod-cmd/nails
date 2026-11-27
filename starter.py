import argparse
import json
from pathlib import Path

from pydantic import Field, ValidationError

from calendar_service import lock
from catalog import (PHOTO_LIMIT, Form, PortfolioItem, Profile, Service, photo_variants,
                     save_profile, save_service, save_work, store_photo)
from storage import connect


class StarterProfile(Profile):
    avatar: str = Field(default="", max_length=240)
    cover: str = Field(default="", max_length=240)


class StarterWork(Form):
    image: str = Field(min_length=1, max_length=240)
    caption: str = Field(default="", max_length=250)
    position: int = Field(default=0, ge=0, le=9999)
    service: int | None = Field(default=None, ge=1)
    visible: bool = True


class Starter(Form):
    profile: StarterProfile
    services: list[Service] = Field(min_length=1, max_length=100)
    portfolio: list[StarterWork] = Field(default_factory=list, max_length=30)


def load_starter(config):
    kit = Starter.model_validate_json(config.read_bytes())
    directory = config.resolve().parent
    prepared = {}
    paths = {}

    def prepare(source, field):
        if not source:
            return ""
        if source in paths:
            return paths[source]
        path = (directory / source).resolve()
        if Path(source).is_absolute() or not path.is_relative_to(directory):
            raise ValueError(f"{field}: нужен путь внутри папки комплекта")
        try:
            with path.open("rb") as photo:
                key, variants = photo_variants(photo.read(PHOTO_LIMIT + 1))
        except (ValueError, OSError) as error:
            detail = str(error) if isinstance(error, ValueError) else "Файл недоступен"
            raise ValueError(f"{field} ({source}): {detail}") from None
        paths[source] = key
        prepared[key] = variants
        return key

    for index, service in enumerate(kit.services, 1):
        if service.id is not None or any(addon.id is not None for addon in service.addons):
            raise ValueError(f"services[{index}]: уберите идентификаторы услуг и дополнений")

    profile = Profile.model_validate(kit.profile.model_dump() | {
        "avatar": prepare(kit.profile.avatar, "profile.avatar"),
        "cover": prepare(kit.profile.cover, "profile.cover"),
    })
    works = []
    for index, work in enumerate(kit.portfolio, 1):
        if work.service is not None and work.service > len(kit.services):
            raise ValueError(f"portfolio[{index}].service: услуги с таким номером нет")
        works.append((PortfolioItem(image=prepare(work.image, f"portfolio[{index}].image"),
            caption=work.caption, position=work.position, visible=work.visible), work.service))
    return profile, kit.services, works, prepared


def import_starter(config):
    profile, catalog, works, prepared = load_starter(config)
    with connect() as db:
        lock(db)
        row = db.execute("""SELECT configured OR EXISTS (SELECT 1 FROM services)
            OR EXISTS (SELECT 1 FROM visits) OR EXISTS (SELECT 1 FROM portfolio)
            OR EXISTS (SELECT 1 FROM subscriptions) OR EXISTS (SELECT 1 FROM events)
            OR EXISTS (SELECT 1 FROM breaks) OR EXISTS (SELECT 1 FROM week_hours)
            OR EXISTS (SELECT 1 FROM exceptions)
            OR step <> 60 OR horizon <> 30 OR lead_hours <> 0 AS occupied FROM profile WHERE id=1""").fetchone()
        if not row or row["occupied"]:
            raise ValueError("Импорт доступен только для пустого экземпляра")
        apply_starter(db, profile, catalog, works, prepared)


def apply_starter(db, profile, catalog, works, prepared):
    for key, variants in prepared.items():
        store_photo(key, variants, db=db)
    save_profile(db, profile)
    ids = [save_service(db, service) for service in catalog]
    for work, index in works:
        work.service_id = ids[index - 1] if index else None
        save_work(db, work)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Импорт стартового комплекта в пустой экземпляр")
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    try:
        import_starter(args.config)
    except ValidationError as error:
        failures = [".".join(map(str, item["loc"])) + " · проверьте значение"
                    for item in error.errors()]
        raise SystemExit("Проверьте комплект:\n" + "\n".join(failures)) from None
    except OSError:
        raise SystemExit("Не удалось прочитать комплект или записать фото в хранилище") from None
    except ValueError as error:
        raise SystemExit(str(error)) from None
    print("Стартовый комплект загружен.")
