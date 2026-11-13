"""Inventario de licencias de las dependencias Python INSTALADAS (metadatos de cada paquete).

Genera docs/licenses/python-dependencies.md. Con --check falla si aparece una licencia
copyleft fuerte (GPL/AGPL/SSPL) o desconocida en dependencias de runtime no revisadas.
"""

from __future__ import annotations

import re
import sys
from importlib.metadata import distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/licenses/python-dependencies.md"
STRONG_COPYLEFT = re.compile(r"\b(A?GPL|SSPL|GNU General Public|Affero)\b(?!.*Lesser)", re.IGNORECASE)
# Revisadas manualmente: (paquete -> justificación)
REVIEWED = {
    "psycopg2": "no usado",
}


def license_of(dist) -> str:
    md = dist.metadata
    expr = md.get("License-Expression")
    if expr:
        return expr
    classifiers = [c.split("::")[-1].strip() for c in md.get_all("Classifier") or [] if c.startswith("License ::")]
    if classifiers:
        return "; ".join(classifiers)
    lic = (md.get("License") or "").strip()
    return lic.splitlines()[0][:80] if lic else "DESCONOCIDA"


def main() -> int:
    rows = []
    problems = []
    for d in sorted(distributions(), key=lambda d: d.metadata["Name"].lower()):
        name = d.metadata["Name"]
        if name == "security-vision":
            continue
        lic = license_of(d)
        flag = ""
        if name.lower() not in REVIEWED and (lic == "DESCONOCIDA" or STRONG_COPYLEFT.search(lic)):
            flag = "⚠️ revisar"
            problems.append(f"{name}: {lic}")
        rows.append(f"| {name} | {d.version} | {lic} | {flag} |")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "# Licencias de dependencias Python (generado)\n\n"
        "Fuente: metadatos de los paquetes instalados en el entorno (`uv sync --extra ml` + grupo dev). "
        "Regenerar con `uv run python scripts/license_report.py`.\n\n"
        "| Paquete | Versión | Licencia declarada | Estado |\n|---|---|---|---|\n" + "\n".join(rows) + "\n",
        encoding="utf-8")
    print(f"{len(rows)} paquetes -> {OUT.relative_to(ROOT)}")
    for p in problems:
        print(f"  revisar: {p}")
    return 1 if ("--check" in sys.argv and problems) else 0


if __name__ == "__main__":
    sys.exit(main())
