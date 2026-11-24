import argparse
import base64
import getpass
import hashlib
import json
import os
import re
import secrets
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def encoded(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()


def settings(password, email):
    salt = secrets.token_hex(16)
    key = ec.generate_private_key(ec.SECP256R1())
    return dict(ADMIN_HASH=salt+"."+password_hash(password, salt),
                SESSION_SECRET=secrets.token_urlsafe(48), CRON_SECRET=secrets.token_urlsafe(40),
                POSTGRES_PASSWORD=secrets.token_hex(24), VAPID_EMAIL=email,
                VAPID_PRIVATE=encoded(key.private_bytes(serialization.Encoding.DER,
                    serialization.PrivateFormat.PKCS8, serialization.NoEncryption())),
                VAPID_PUBLIC=encoded(key.public_key().public_bytes(serialization.Encoding.X962,
                    serialization.PublicFormat.UncompressedPoint)))


def credentials():
    password = getpass.getpass("Пароль мастера (от 12 символов): ")
    email = input("Email владельца для VAPID: ").strip()
    if (len(password) < 12 or
        not re.fullmatch(r"[A-Za-z0-9.!%+_-]+@[A-Za-z0-9.-]+", email)):
        raise SystemExit("Проверьте пароль и email")
    return settings(password, email)


def write_env(path, values):
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            for key, value in values.items():
                output.write(f"{key}={value}\n")
    except FileExistsError:
        raise SystemExit("Файл настроек уже существует") from None


def create_instance(args):
    root = Path(__file__).resolve().parent
    name = args.id
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", name) or not 1 <= args.port <= 65535:
        raise SystemExit("Проверьте идентификатор и локальный порт")
    address = urlsplit(args.url)
    if (address.scheme not in {"http", "https"} or not address.hostname or address.username
        or address.password or address.path not in {"", "/"} or address.query or address.fragment
        or not re.fullmatch(r"[A-Za-z0-9.:-]+", address.netloc)):
        raise SystemExit("Укажите адрес сайта с протоколом, без пути и параметров")
    if not re.fullmatch(r"[A-Za-z0-9._:/@-]+", args.image):
        raise SystemExit("Проверьте имя образа приложения")
    folder = root / "instances" / name
    if folder.exists():
        raise SystemExit("Экземпляр с таким идентификатором уже существует")
    kit = args.starter.resolve() if args.starter else None
    if kit:
        from starter import load_starter
        from pydantic import ValidationError

        try:
            load_starter(kit)
        except ValidationError as error:
            fields = ", ".join(".".join(map(str, item["loc"])) for item in error.errors())
            raise SystemExit("Проверьте поля комплекта · " + fields) from None
        except ValueError as error:
            raise SystemExit(str(error)) from None
        except OSError:
            raise SystemExit("Файл комплекта недоступен") from None

    compose = ["docker", "compose", "--project-name", f"booking-{name}"]
    try:
        existing = subprocess.check_output(
            ["docker", "compose", "ls", "-a", "--format", "json"], cwd=root, text=True)
    except (OSError, subprocess.CalledProcessError):
        raise SystemExit("Не удалось получить список экземпляров Docker Compose") from None

    if any(project["Name"] == f"booking-{name}" for project in json.loads(existing)):
        raise SystemExit("Экземпляр с таким идентификатором уже существует")
    if subprocess.run(["docker", "image", "inspect", args.image], cwd=root,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        raise SystemExit("Сначала соберите или загрузите общий образ " + args.image)
    values = credentials()
    relative_env = Path("instances", name, "settings.env").as_posix()
    try:
        folder.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise SystemExit("Экземпляр с таким идентификатором уже существует") from None
    write_env(root / relative_env, values | {"INSTANCE_ENV": relative_env, "PORT": args.port,
        "PUBLIC_URL": args.url, "APP_IMAGE": args.image})
    compose += ["--env-file", relative_env, "--profile", "local"]

    try:
        subprocess.run([*compose, "up", "-d", "--wait", "db"], cwd=root, check=True)
        subprocess.run([*compose, "run", "--rm", "--no-deps", "web", "python", "-m", "storage", "--empty"],
                       cwd=root, check=True)
        if kit:
            subprocess.run([*compose, "run", "--rm", "--no-deps", "--volume",
                f"{kit.parent}:/starter:ro", "web", "python", "-m", "starter", f"/starter/{kit.name}"],
                cwd=root, check=True)
        subprocess.run([*compose, "up", "-d", "--no-build", "web", "worker"], cwd=root, check=True)
    except subprocess.CalledProcessError:
        raise SystemExit(f"Запуск прерван. Настройки сохранены в {relative_env}") from None
    print(f"Экземпляр {name} запущен. Витрина {args.url.rstrip('/')} · кабинет /admin")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="Файл для новых настроек")
    commands = parser.add_subparsers(dest="command")
    create = commands.add_parser("instance", help="Создать отдельный экземпляр через Docker Compose")
    create.add_argument("id", help="Уникальный идентификатор")
    create.add_argument("--port", type=int, required=True)
    create.add_argument("--url", required=True)
    create.add_argument("--starter", type=Path)
    create.add_argument("--image", default="nail-studio:local")
    options = parser.parse_args()
    if options.command == "instance":
        create_instance(options)
    else:
        if options.env_file.exists():
            raise SystemExit("Файл настроек уже существует")
        write_env(options.env_file, credentials())
