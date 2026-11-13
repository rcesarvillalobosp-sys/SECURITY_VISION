"""Exporta la especificación OpenAPI de la API y una tabla de endpoints con su permiso requerido.

    uv run python scripts/export_openapi.py          # escribe docs/api/openapi.json y docs/api/endpoints.md
    uv run python scripts/export_openapi.py --check  # falla si los archivos no están al día (CI)

El permiso se obtiene de la dependencia ``require(Permission.X)`` de cada ruta: la tabla refleja el control
de acceso real del código, no una descripción escrita a mano.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/api"


def _permission_of(route) -> str:
    """Busca en las dependencias de la ruta el cierre de ``require(...)`` y devuelve sus permisos."""
    found: list[str] = []

    def walk(dep) -> None:
        call = getattr(dep, "call", None)
        closure = getattr(call, "__closure__", None) or ()
        for cell in closure:
            v = cell.cell_contents
            if isinstance(v, tuple) and v and all(hasattr(p, "value") and ":" in str(p.value) for p in v):
                found.extend(str(p.value) for p in v)
        for sub in getattr(dep, "dependencies", []):
            walk(sub)

    walk(route.dependant)
    if found:
        return ", ".join(sorted(set(found)))
    names = {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}
    return "sesión" if "get_principal" in str(names) or any("principal" in n for n in names) else "pública"


def build() -> tuple[str, str]:
    import os

    os.environ.setdefault("SV_DATABASE_URL", "postgresql+asyncpg://u:p@127.0.0.1:1/x")
    os.environ.setdefault("SV_JWT_SECRET", "x" * 48)
    os.environ.setdefault("SV_SECRETS_KEY", "A" * 43 + "=")
    from fastapi.routing import APIRoute

    from security_vision.core.configuration.settings import Settings
    from security_vision_api.main import create_app

    settings = Settings(_env_file=None, environment="development", web_dist=None)  # type: ignore[call-arg]
    app = create_app(settings)
    spec = app.openapi()
    spec_text = json.dumps(spec, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    def iter_routes(routes):
        for r in routes:
            inner = getattr(r, "original_router", None)
            if inner is not None:
                yield from iter_routes(inner.routes)
            else:
                yield r

    rows = []
    for r in iter_routes(app.routes):
        if isinstance(r, APIRoute) and r.include_in_schema:
            for m in sorted(r.methods - {"HEAD"}):
                summary = (r.description or r.summary or r.name).strip().splitlines()[0] if (
                    r.description or r.summary) else r.name.replace("_", " ")
                rows.append((r.path, m, _permission_of(r), summary, (r.tags or ["—"])[0]))
    rows.sort()
    md = ["# API REST: endpoints", "",
          f"Generado por `scripts/export_openapi.py` a partir del código (versión {spec['info']['version']}). "
          "Especificación completa: [openapi.json](openapi.json). En desarrollo, documentación interactiva en "
          "`/docs` (desactivada en producción).", "",
          "- **Autenticación:** `Authorization: Bearer <token de acceso>` (`POST /api/v1/auth/login`; renovación "
          "con la cookie httpOnly `sv_refresh` en `POST /api/v1/auth/refresh`).",
          "- **Errores:** JSON `{\"detail\": ..., \"code\": ...}` con 401/403/404/409/422.",
          "- **Tiempo real:** WebSocket `/api/v1/ws` (autenticación en el primer mensaje "
          "`{\"type\":\"auth\",\"token\":...}`).",
          "- **Fuera de la especificación:** `/metrics` (solo redes permitidas), "
          "`/api/v1/files/...` (evidencias con URL firmada) y `/api/v1/media/auth` (uso interno de MediaMTX).", "",
          "| Método | Ruta | Permiso | Área | Operación |", "|---|---|---|---|---|"]
    md += [f"| {m} | `{p}` | {perm} | {tag} | {desc} |" for p, m, perm, desc, tag in rows]
    return spec_text, "\n".join(md) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    spec, md = build()
    files = {OUT / "openapi.json": spec, OUT / "endpoints.md": md}
    if a.check:
        stale = [str(p.relative_to(ROOT)) for p, content in files.items()
                 if not p.exists() or p.read_text(encoding="utf-8") != content]
        if stale:
            sys.exit(f"documentación de la API desactualizada: {stale} (ejecutar scripts/export_openapi.py)")
        print("documentación de la API al día")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    for p, content in files.items():
        p.write_text(content, encoding="utf-8", newline="\n")
    print(f"{sum(1 for line in md.splitlines() if line.startswith('| ') and '`' in line)} endpoints -> {OUT}")


if __name__ == "__main__":
    main()
