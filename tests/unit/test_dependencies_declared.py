"""Cada paquete de terceros que importa el producto debe estar declarado donde el producto lo instala.

Lo detectó la instalación limpia de la Fase 10: el worker importaba ``scipy`` (asignación húngara), que solo
estaba en el extra ``train``. En desarrollo funcionaba porque el entorno tenía ese extra; en producción y en la
imagen Docker del worker no habría arrancado.
"""

from __future__ import annotations

import ast
import importlib.metadata as md
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRODUCT = [ROOT / "src/security_vision", ROOT / "apps/api/security_vision_api",
           ROOT / "apps/processing-worker/security_vision_worker"]
# Extras que una instalación del producto puede usar (opcionales y con importación protegida)
RUNTIME_EXTRAS = {"inference", "otel"}


def _norm(name: str) -> str:
    return re.split(r"[<>=\[ ;]", name)[0].lower().replace("_", "-")


def test_product_imports_are_declared_as_runtime_dependencies():
    imported: set[str] = set()
    for base in PRODUCT:
        for f in base.rglob("*.py"):
            for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if isinstance(n, ast.Import):
                    imported |= {a.name.split(".")[0] for a in n.names}
                elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                    imported.add(n.module.split(".")[0])
    third = {m for m in imported if m not in sys.stdlib_module_names and not m.startswith("security_vision")}
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    allowed = {_norm(d) for d in cfg["dependencies"]}
    for extra in RUNTIME_EXTRAS:
        allowed |= {_norm(d) for d in cfg["optional-dependencies"][extra]}
    dists = md.packages_distributions()
    missing = {}
    for mod in sorted(third):
        names = {_norm(d) for d in dists.get(mod, [mod])}
        if not names & allowed:
            missing[mod] = sorted(names)
    assert not missing, f"importados por el producto pero no declarados para producción: {missing}"
