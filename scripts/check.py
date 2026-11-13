"""CI local: el mismo conjunto de verificaciones que el workflow de CI.

    uv run python scripts/check.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

STEPS = [
    ("ruff (lint)", ["ruff", "check", "src", "apps", "tests", "scripts", "ml"]),
    ("import-linter (arquitectura)", ["lint-imports"]),
    ("alembic check (modelo == migraciones)", ["alembic", "check"]),
    ("pytest", ["pytest", "-q", "-p", "no:cacheprovider"]),
    ("licencias de dependencias", [sys.executable, "scripts/license_report.py", "--check"]),
    ("documentación de la API (OpenAPI)", [sys.executable, "scripts/export_openapi.py", "--check"]),
]
# Frontend (si está instalado): tipos, tests y licencias de las dependencias empaquetadas
if Path("apps/web/node_modules").exists():
    NPM = "npm.cmd" if sys.platform.startswith("win") else "npm"
    STEPS += [
        ("web: tipos (tsc)", [NPM, "--prefix", "apps/web", "run", "typecheck"]),
        ("web: tests (vitest)", [NPM, "--prefix", "apps/web", "run", "test"]),
        ("web: licencias", ["node", "scripts/web_license_report.mjs", "apps/web", "--check"]),
    ]


def main() -> int:
    failed = []
    for name, cmd in STEPS:
        print(f"\n==> {name}", flush=True)
        if subprocess.run(cmd).returncode != 0:
            failed.append(name)
    print("\nRESULTADO:", "OK" if not failed else f"FALLÓ: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
