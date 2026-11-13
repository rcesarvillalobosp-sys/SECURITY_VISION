"""Copia de seguridad y restauración de PostgreSQL + evidencias (instalación nativa).

    uv run python scripts/backup.py create --out D:/backups              # BD (pg_dump -Fc) + evidencias (zip)
    uv run python scripts/backup.py verify --dump D:/backups/sv-....dump --scratch-db security_vision_test
                                          # restaura en una BD desechable (se SOBRESCRIBE) y compara
    uv run python scripts/backup.py restore --dump ... --target-db security_vision   # ¡sobrescribe!

Usa los binarios de PostgreSQL (SV_PG_HOME o el PATH). La contraseña se pasa por PGPASSWORD (nunca en la
línea de comandos). ``verify`` es la única forma honesta de saber que una copia sirve: se restaura y se
cuentan filas tabla por tabla frente al origen.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
TABLES = ["users", "cameras", "zones", "security_profiles", "incidents", "evidences", "detections",
          "incident_history", "incident_comments", "audit_log", "alert_channels", "alert_deliveries", "camera_stats"]


def _pg_bin(name: str) -> str:
    home = os.environ.get("SV_PG_HOME")
    if not home:
        from dev_postgres import read_env  # type: ignore[import-not-found]

        home = read_env().get("SV_PG_HOME")
    exe = name + (".exe" if os.name == "nt" else "")
    if home and (Path(home) / "bin" / exe).exists():
        return str(Path(home) / "bin" / exe)
    found = shutil.which(name)
    if not found:
        sys.exit(f"no se encuentra {name}: definir SV_PG_HOME (carpeta con bin/) o añadirlo al PATH")
    return found


def _conn() -> dict[str, str]:
    from security_vision.core.configuration.settings import get_settings

    u = urlsplit(get_settings().database_url.get_secret_value().replace("+asyncpg", ""))
    return {"host": u.hostname or "127.0.0.1", "port": str(u.port or 5432), "user": u.username or "",
            "password": u.password or "", "db": u.path.lstrip("/")}


def _env(c: dict[str, str]) -> dict[str, str]:
    return os.environ | {"PGPASSWORD": c["password"]}


def _run(args: list[str], c: dict[str, str]) -> None:
    r = subprocess.run(args, env=_env(c), capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"{Path(args[0]).name} falló: {r.stderr.strip()[:500]}")


async def _counts(db: str, c: dict[str, str]) -> dict[str, int]:
    import asyncpg

    conn = await asyncpg.connect(host=c["host"], port=int(c["port"]), user=c["user"], password=c["password"],
                                 database=db)
    try:
        return {t: await conn.fetchval(f'SELECT count(*) FROM "{t}"') for t in TABLES}
    finally:
        await conn.close()


def create(out: Path) -> None:
    from security_vision.core.configuration.settings import get_settings

    c = _conn()
    out.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    dump = out / f"sv-{stamp}.dump"
    _run([_pg_bin("pg_dump"), "-h", c["host"], "-p", c["port"], "-U", c["user"], "-d", c["db"], "-Fc",
          "--no-owner", "-f", str(dump)], c)
    storage = Path(get_settings().storage_dir)
    archive = out / f"sv-{stamp}-evidencias.zip"
    n = 0
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as z:  # JPEG ya comprimido
        if storage.exists():
            for f in storage.rglob("*"):
                if f.is_file():
                    z.write(f, f.relative_to(storage))
                    n += 1
    print(f"BD: {dump} ({dump.stat().st_size / 1e6:.1f} MB) · evidencias: {archive} ({n} archivos)")


def verify(dump: Path, scratch: str) -> None:
    """Restaura en ``scratch`` (base desechable que el rol de la aplicación ya posee: no se necesita el
    privilegio CREATEDB) y compara filas con la base en uso."""
    c = _conn()
    if scratch == c["db"]:
        sys.exit("la base desechable no puede ser la base en uso")
    base = ["-h", c["host"], "-p", c["port"], "-U", c["user"]]
    _run([_pg_bin("pg_restore"), *base, "-d", scratch, "--clean", "--if-exists", "--no-owner",
          "--exit-on-error", str(dump)], c)
    src, dst = asyncio.run(_counts(c["db"], c)), asyncio.run(_counts(scratch, c))
    width = max(map(len, TABLES))
    bad = 0
    for t in TABLES:
        mark = "OK" if src[t] == dst[t] else "DIFERENTE (¿cambios después de la copia?)"
        bad += src[t] != dst[t]
        print(f"  {t:<{width}}  origen {src[t]:>7}  restaurada {dst[t]:>7}  {mark}")
    print("copia restaurable y completa" if not bad else f"{bad} tabla(s) difieren")


def restore(dump: Path, target: str) -> None:
    c = _conn()
    base = ["-h", c["host"], "-p", c["port"], "-U", c["user"]]
    _run([_pg_bin("pg_restore"), *base, "-d", target, "--clean", "--if-exists", "--no-owner", str(dump)], c)
    print(f"restaurada en {target}. Recuerda restaurar también el zip de evidencias en SV_STORAGE_DIR.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("create").add_argument("--out", type=Path, required=True)
    v = sub.add_parser("verify")
    v.add_argument("--dump", type=Path, required=True)
    v.add_argument("--scratch-db", required=True, help="base desechable donde restaurar (se sobrescribe)")
    r = sub.add_parser("restore")
    r.add_argument("--dump", type=Path, required=True)
    r.add_argument("--target-db", required=True)
    a = ap.parse_args()
    if a.cmd == "create":
        create(a.out)
    elif a.cmd == "verify":
        verify(a.dump, a.scratch_db)
    else:
        restore(a.dump, a.target_db)


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "scripts"))
    main()
