"""PostgreSQL local de desarrollo SIN Docker ni permisos de administrador.

Usa los binarios portables de PostgreSQL (EDB) indicados en SV_PG_HOME (carpeta que contiene bin/).
El clúster vive fuera del repositorio y solo escucha en 127.0.0.1.

    uv run python scripts/dev_postgres.py init     # initdb + roles + bases de datos (una vez)
    uv run python scripts/dev_postgres.py start | stop | status

Lee/escribe credenciales en .env (nunca las imprime).
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
DEFAULT_BASE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "security-vision"
PORT = int(os.environ.get("SV_PG_PORT", "5433"))


def read_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def write_env(updates: dict[str, str]) -> None:
    env = read_env()
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    for k, v in updates.items():
        if k in env:
            lines = [f"{k}={v}" if ln.split("=", 1)[0].strip() == k else ln for ln in lines]
        else:
            lines.append(f"{k}={v}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def pg_home() -> Path:
    home = os.environ.get("SV_PG_HOME") or read_env().get("SV_PG_HOME") or str(DEFAULT_BASE / "pg17" / "pgsql")
    p = Path(home)
    if not (p / "bin").exists():
        sys.exit(f"No se encuentran los binarios de PostgreSQL en {p}/bin (defina SV_PG_HOME)")
    return p


def data_dir() -> Path:
    return Path(read_env().get("SV_PG_DATA", str(DEFAULT_BASE / "pgdata")))


def run(*args: str, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, capture_output=True, env={**os.environ, **(env or {})})


def bin_(name: str) -> str:
    return str(pg_home() / "bin" / name)


def psql(sql: str, password: str, db: str = "postgres") -> None:
    run(bin_("psql"), "-h", "127.0.0.1", "-p", str(PORT), "-U", "postgres", "-d", db, "-v", "ON_ERROR_STOP=1",
        "-c", sql, env={"PGPASSWORD": password})


def cmd_init() -> None:
    d = data_dir()
    if (d / "PG_VERSION").exists():
        print(f"El clúster ya existe en {d}")
        return
    su_pwd = secrets.token_urlsafe(24)
    app_pwd = secrets.token_urlsafe(24)
    d.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".pw") as fh:
        fh.write(su_pwd)
        pwfile = fh.name
    try:
        run(bin_("initdb"), "-D", str(d), "-U", "postgres", "--auth=scram-sha-256", f"--pwfile={pwfile}",
            "-E", "UTF8", "--locale=C")
    finally:
        os.unlink(pwfile)
    with (d / "postgresql.conf").open("a", encoding="utf-8") as fh:
        fh.write(f"\nlisten_addresses = '127.0.0.1'\nport = {PORT}\n")
    write_env({"SV_PG_DATA": str(d), "SV_PG_HOME": str(pg_home()), "SV_PG_SUPERUSER_PASSWORD": su_pwd})
    cmd_start()
    psql(f"CREATE ROLE security_vision LOGIN PASSWORD '{app_pwd}'", su_pwd)
    for db in ("security_vision", "security_vision_test"):
        psql(f"CREATE DATABASE {db} OWNER security_vision", su_pwd)
    url = f"postgresql+asyncpg://security_vision:{app_pwd}@127.0.0.1:{PORT}"
    write_env({"SV_DATABASE_URL": f"{url}/security_vision", "SV_TEST_DATABASE_URL": f"{url}/security_vision_test"})
    print(f"Clúster creado en {d}; credenciales guardadas en .env")


def cmd_start() -> None:
    d = data_dir()
    if run(bin_("pg_ctl"), "status", "-D", str(d), check=False).returncode == 0:
        print("PostgreSQL ya está en marcha")
        return
    log = d.parent / "postgres.log"
    # pg_ctl start deja el servidor en segundo plano y vuelve.
    subprocess.run([bin_("pg_ctl"), "start", "-D", str(d), "-l", str(log), "-w", "-t", "60"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    for _ in range(30):
        if run(bin_("pg_isready"), "-h", "127.0.0.1", "-p", str(PORT), check=False).returncode == 0:
            print(f"PostgreSQL escuchando en 127.0.0.1:{PORT}")
            return
        time.sleep(1)
    sys.exit(f"PostgreSQL no respondió; ver {log}")


def cmd_stop() -> None:
    run(bin_("pg_ctl"), "stop", "-D", str(data_dir()), "-m", "fast", check=False)
    print("PostgreSQL detenido")


def cmd_status() -> None:
    r = run(bin_("pg_isready"), "-h", "127.0.0.1", "-p", str(PORT), check=False)
    print(r.stdout.strip() or r.stderr.strip())


if __name__ == "__main__":
    commands = {"init": cmd_init, "start": cmd_start, "stop": cmd_stop, "status": cmd_status}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(f"uso: {Path(__file__).name} {{{'|'.join(commands)}}}")
    commands[sys.argv[1]]()
