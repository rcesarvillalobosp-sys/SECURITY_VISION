"""``svctl doctor``: comprobación previa al arranque o tras una instalación.

Cada comprobación devuelve OK, AVISO o ERROR con un mensaje accionable. No muestra secretos.
Código de salida 1 si hay algún ERROR.
"""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path

from security_vision.core.configuration.settings import Environment, Settings

ROOT = Path(__file__).resolve().parents[3]


@dataclass
class Check:
    name: str
    level: str  # OK | AVISO | ERROR
    detail: str


async def _db(s: Settings) -> list[Check]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import text

    from security_vision.infrastructure.database.session import create_engine

    out: list[Check] = []
    engine = create_engine(s.database_url.get_secret_value(), pool_size=1)
    try:
        async with engine.connect() as conn:
            version = (await conn.execute(text("SHOW server_version"))).scalar()
            out.append(Check("PostgreSQL", "OK", f"conecta (versión {version})"))
            try:
                current = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
            except Exception:
                current = None
            users = (await conn.execute(text("SELECT count(*) FROM users"))).scalar() if current else 0
    except Exception as exc:
        return [Check("PostgreSQL", "ERROR", f"no conecta: {type(exc).__name__} (¿arrancado? ¿SV_DATABASE_URL?)")]
    finally:
        await engine.dispose()
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "src/security_vision/infrastructure/database/migrations"))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    if current == head:
        out.append(Check("Migraciones", "OK", f"en la última versión ({head})"))
    else:
        out.append(Check("Migraciones", "ERROR", f"base de datos en {current or 'vacía'}, código en {head}: "
                                                 "ejecutar `svctl migrate`"))
    out.append(Check("Usuarios", "OK" if users else "ERROR",
                     f"{users} usuario(s)" if users else "no hay usuarios: ejecutar `svctl bootstrap`"))
    return out


def _model(s: Settings) -> list[Check]:
    if not s.detection_model:
        return [Check("Modelo", "AVISO", "SV_DETECTION_MODEL vacío: el worker capturará sin detección")]
    from security_vision.infrastructure.models.store import RegistryModelCatalog
    from security_vision.plugins.inference_engines.common import verify_artifact

    reg_dir = Path(s.model_registry_dir)  # relativo al directorio de trabajo, como el worker
    info = RegistryModelCatalog(reg_dir).get(s.detection_model)
    if info is None or info.spec is None:
        return [Check("Modelo", "ERROR", f"{s.detection_model} no está en el registro")]
    if not info.artifact_present:
        return [Check("Modelo", "ERROR", f"{s.detection_model}: {info.error}")]
    from security_vision.infrastructure.models.store import ModelStore

    try:
        reg = ModelStore(reg_dir).get(s.detection_model)
        verify_artifact(reg.artifact)
    except Exception as exc:
        return [Check("Modelo", "ERROR", f"{s.detection_model}: {exc}")]
    return [Check("Modelo", "OK", f"{s.detection_model} presente y con sha256 correcto")]


def _inference(s: Settings) -> list[Check]:
    try:
        import onnxruntime as ort
    except ImportError:
        return [Check("Inferencia", "AVISO",
                      "ONNX Runtime no instalado (worker sin detección): uv sync --extra inference")]
    avail = ort.get_available_providers()
    wanted = s.inference_devices
    if "cuda" in wanted and "CUDAExecutionProvider" not in avail:
        return [Check("Inferencia", "AVISO", f"se pidió CUDA pero no está disponible; proveedores: {avail}")]
    gpu = ""
    try:
        import pynvml

        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        name = pynvml.nvmlDeviceGetName(h)
        gpu = f" · GPU {name}, estado P{pynvml.nvmlDeviceGetPerformanceState(h)}"
    except Exception:
        pass
    names = ", ".join(p.replace("ExecutionProvider", "") for p in avail)
    return [Check("Inferencia", "OK", f"proveedores {names}{gpu}")]


def _storage(s: Settings) -> list[Check]:
    p = Path(s.storage_dir)
    try:
        p.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=p, delete=True):
            pass
    except OSError as exc:
        return [Check("Almacenamiento", "ERROR", f"{p} no es escribible: {exc}")]
    import shutil

    free = shutil.disk_usage(p).free / 2**30
    return [Check("Almacenamiento", "OK" if free > 5 else "AVISO", f"{p.resolve()} · {free:.0f} GB libres")]


async def _media(s: Settings) -> list[Check]:
    if not s.mediamtx_api_url:
        return [Check("MediaMTX", "AVISO", "no configurado: sin vídeo en directo en la web")]
    import httpx

    pwd = s.mediamtx_api_password.get_secret_value() if s.mediamtx_api_password else ""
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{s.mediamtx_api_url.rstrip('/')}/v3/paths/list",
                            auth=(s.mediamtx_api_user or "", pwd))
    except httpx.HTTPError as exc:
        return [Check("MediaMTX", "ERROR", f"API no accesible ({type(exc).__name__}): ¿arrancado?")]
    if r.status_code in (401, 403):
        return [Check("MediaMTX", "ERROR", f"la API rechaza las credenciales (HTTP {r.status_code}); si usa "
                                           "autenticación HTTP, la API de Security Vision debe estar en marcha")]
    out = [Check("MediaMTX", "OK" if r.status_code == 200 else "AVISO", f"API responde HTTP {r.status_code}")]
    if not s.mediamtx_auth_key:
        out.append(Check("MediaMTX: autorización", "AVISO", "SV_MEDIAMTX_AUTH_KEY vacío: la lectura WebRTC solo "
                                                         "funcionará con MediaMTX en modo interno (localhost)"))
    return out


def _security(s: Settings) -> list[Check]:
    out: list[Check] = []
    prod = s.environment is Environment.PRODUCTION
    if not prod:
        out.append(Check("Entorno", "AVISO", f"SV_ENVIRONMENT={s.environment.value} (usar production al desplegar)"))
    else:
        out.append(Check("Entorno", "OK", "production (guardas de configuración activas)"))
    if s.allow_test_sources:
        out.append(Check("Fuentes de prueba", "AVISO", "SV_ALLOW_TEST_SOURCES=true (solo desarrollo)"))
    if s.alert_webhook_allow_private:
        out.append(Check("Webhooks", "AVISO", "SV_ALERT_WEBHOOK_ALLOW_PRIVATE=true: se permiten destinos de red "
                                             "privada (riesgo SSRF)"))
    if s.bootstrap_admin_password:
        out.append(Check("Admin inicial", "AVISO", "SV_BOOTSTRAP_ADMIN_PASSWORD sigue definido: quitarlo de .env "
                                                  "tras el primer arranque y cambiar la contraseña"))
    if s.web_dist and not (Path(s.web_dist) / "index.html").exists():
        out.append(Check("Web", "ERROR", f"SV_WEB_DIST={s.web_dist} no contiene index.html: `npm run build`"))
    elif s.web_dist:
        out.append(Check("Web", "OK", f"frontend compilado en {s.web_dist}"))
    return out


async def run_doctor(s: Settings) -> list[Check]:
    checks = await _db(s)
    checks += _model(s) + _inference(s) + _storage(s)
    checks += await _media(s)
    checks += _security(s)
    return checks


def main(s: Settings) -> int:
    checks = asyncio.run(run_doctor(s))
    width = max(len(c.name) for c in checks)
    for c in checks:
        print(f"[{c.level:5s}] {c.name:<{width}}  {c.detail}")
    errors = sum(c.level == "ERROR" for c in checks)
    print(f"\n{len(checks)} comprobaciones · {errors} error(es) · {sum(c.level == 'AVISO' for c in checks)} aviso(s)")
    return 1 if errors else 0
