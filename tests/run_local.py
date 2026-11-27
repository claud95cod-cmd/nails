"""Прогон на одноразовом локальном PostgreSQL. Существующие базы не используются."""
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from configure import settings

def run():
    source = root / ".local/node_modules/@embedded-postgres/windows-x64/native"
    password = secrets.token_hex(24)
    with socket.socket() as s:
        s.bind(("127.0.0.1",0))
        port=s.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="master-pg-") as temporary:
        # initdb на Windows требует путь без кириллицы к системным SQL-файлам.
        binary = Path(shutil.copytree(source,Path(temporary)/"runtime"))/"bin"
        data=Path(temporary)/"data"
        pw=Path(temporary)/"initial"
        pw.write_text(password,encoding="ascii")
        subprocess.run([binary/"initdb.exe","-D",data,"-U","master","-A","scram-sha-256",
                        "--pwfile",pw,"--locale=C","--encoding=UTF8"],check=True)
        ctl=[binary/"pg_ctl.exe","-D",data]
        subprocess.run([*ctl,"-l",Path(temporary)/"postgres.log","-o",f"-h 127.0.0.1 -p {port}","-w","start"],check=True)
        try:
            env=dict(os.environ,**settings(password,"test@example.org"))
            env.update(DATABASE_URL=f"postgresql://master:{password}@127.0.0.1:{port}/postgres",
                       MASTER_CABINET_ENABLED="1",TEST_MASTER_PASSWORD=password,TEST_DISPOSABLE_DATABASE="1",
                       TEST_POSTGRES_BIN=str(binary),TEST_POSTGRES_DATA=str(data))
            return subprocess.call([sys.executable,"-m","pytest","-q","tests",*sys.argv[1:]],cwd=root,env=env)
        finally:
            subprocess.run([*ctl,"-m","fast","-w","stop"],check=True)

if __name__=="__main__":
    sys.exit(run())
