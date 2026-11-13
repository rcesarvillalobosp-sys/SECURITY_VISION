"""Capa de correcciones de anotaciones (re-etiquetado en CVAT) sobre datos originales inmutables.

Flujo:
1. ``export_review_package``: genera un paquete para CVAT con todas las imágenes que
   contienen una clase dudosa y TODAS sus cajas (contexto completo), y registra la
   corrección como ``pending`` en ``ml/datasets/corrections/<fuente>/<id>/``.
2. El revisor corrige en CVAT y exporta "COCO 1.0" (sin imágenes). El JSON se guarda
   como ``instances_default.json`` en la carpeta de la corrección y ``correction.yaml``
   pasa a ``status: completed``.
3. En la normalización, ``CorrectionSet.apply`` sustituye las cajas de esas imágenes por
   las corregidas (verificando el sha256 de la imagen). Los originales nunca se tocan.

Las correcciones son pequeñas (solo JSON/YAML) y SÍ se versionan en git: son trabajo humano.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

from .formats import coco
from .records import Box, ImageRecord, Issue, Severity
from .sources import SourceManifest

PACKAGE = "package.json"
CORRECTION = "correction.yaml"
CVAT_EXPORT = "instances_default.json"


class CorrectionMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    source_id: str
    source_version: str
    scope_class: str
    status: Literal["pending", "completed"]
    reviewer: str | None = None
    completed_on: date | None = None
    notes: str | None = None


def flat_name(rel_path: str) -> str:
    return rel_path.replace("/", "__")


def export_review_package(records: Sequence[ImageRecord], manifest: SourceManifest, source_class: str,
                          correction_id: str, package_dir: Path, corrections_root: Path) -> dict:
    selected = [r for r in records if any(b.source_class == source_class for b in r.boxes)]
    if not selected:
        raise ValueError(f"ninguna imagen contiene la clase {source_class!r}")
    reg_dir = corrections_root / manifest.id / correction_id
    if reg_dir.exists():
        raise FileExistsError(f"la corrección {correction_id!r} ya existe en {reg_dir}")
    if package_dir.exists():
        raise FileExistsError(f"{package_dir} ya existe")

    categories = list(manifest.class_mapping)
    cat_id = {c: i + 1 for i, c in enumerate(categories)}
    images, annotations, files = [], [], {}
    for img_id, r in enumerate(selected, start=1):
        name = flat_name(r.rel_path)
        dest = package_dir / "images" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(r.abs_path, dest)
        files[name] = {"rel_path": r.rel_path, "sha256": r.sha256}
        images.append({"id": img_id, "file_name": name, "width": r.width, "height": r.height})
        for b in r.boxes:
            if b.source_class not in cat_id:
                continue
            x1, y1 = max(0.0, b.x1) * r.width, max(0.0, b.y1) * r.height
            x2, y2 = min(1.0, b.x2) * r.width, min(1.0, b.y2) * r.height
            annotations.append({
                "id": len(annotations) + 1, "image_id": img_id, "category_id": cat_id[b.source_class],
                "bbox": [round(x1, 2), round(y1, 2), round(x2 - x1, 2), round(y2 - y1, 2)],
                "area": round((x2 - x1) * (y2 - y1), 2), "iscrowd": 0, "segmentation": [],
            })
    coco_json = {
        "info": {"description": f"svds review package {correction_id}"},
        "licenses": [],
        "categories": [{"id": i, "name": c, "supercategory": ""} for c, i in cat_id.items()],
        "images": images,
        "annotations": annotations,
    }
    with zipfile.ZipFile(package_dir / "anotaciones_coco.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("annotations/instances_default.json", json.dumps(coco_json))
    labels = [{"name": c, "type": "rectangle", "attributes": []} for c in categories]
    (package_dir / "labels_cvat.json").write_text(json.dumps(labels, indent=2), encoding="utf-8")

    package = {
        "correction_id": correction_id,
        "source_id": manifest.id,
        "source_version": manifest.version,
        "scope_class": source_class,
        "created_at": datetime.now(UTC).isoformat(),
        "images": files,
        "boxes_in_scope": sum(1 for r in selected for b in r.boxes if b.source_class == source_class),
    }
    (package_dir / PACKAGE).write_text(json.dumps(package, indent=1), encoding="utf-8")
    (package_dir / "INSTRUCCIONES.md").write_text(_instructions(correction_id, source_class, reg_dir),
                                                   encoding="utf-8")
    reg_dir.mkdir(parents=True)
    (reg_dir / PACKAGE).write_text(json.dumps(package, indent=1), encoding="utf-8")
    meta = CorrectionMeta(id=correction_id, source_id=manifest.id, source_version=manifest.version,
                          scope_class=source_class, status="pending")
    (reg_dir / CORRECTION).write_text(yaml.safe_dump(meta.model_dump(mode="json"), allow_unicode=True,
                                                     sort_keys=False), encoding="utf-8")
    return package


def _instructions(cid: str, cls: str, reg_dir: Path) -> str:
    return f"""# Corrección `{cid}` — clase `{cls}`

1. En CVAT: crear un proyecto/tarea con las etiquetas de `labels_cvat.json` (Constructor → Raw)
   y subir TODAS las imágenes de `images/`.
2. En la tarea: Acciones → *Upload annotations* → formato **COCO 1.0** → `anotaciones_coco.zip`.
3. Revisar cada caja `{cls}`:
   - Si el calzado ES bota de trabajo → cambiar la etiqueta a `boots`.
   - Si el pie no es visible o no se puede juzgar → borrar la caja (no anotar lo no verificable).
   - Corregir también cualquier otro error evidente que se vea en la imagen.
4. Exportar la tarea en **COCO 1.0** SIN marcar "Save images".
5. Copiar `annotations/instances_default.json` del zip exportado a `{reg_dir.as_posix()}/`.
6. Editar `{reg_dir.as_posix()}/correction.yaml`: `status: completed`, `reviewer`, `completed_on`, `notes`.
7. Ejecutar `uv run svds audit`.
"""


@dataclass
class _Applied:
    meta: CorrectionMeta
    by_rel_path: dict[str, tuple[str | None, list[Box]]]  # rel_path -> (sha256 esperado, cajas)


@dataclass
class CorrectionSet:
    applied: list[_Applied] = field(default_factory=list)
    pending: list[CorrectionMeta] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, corrections_root: Path, manifest: SourceManifest) -> CorrectionSet:
        out = cls()
        base = corrections_root / manifest.id
        if not base.exists():
            return out
        for d in sorted(p for p in base.iterdir() if p.is_dir()):
            meta = CorrectionMeta.model_validate(yaml.safe_load((d / CORRECTION).read_text(encoding="utf-8")))
            if meta.source_version != manifest.version:
                out.problems.append(f"{meta.id}: hecha sobre la versión {meta.source_version}, "
                                    f"la actual es {manifest.version}; no se aplica")
                continue
            export = d / CVAT_EXPORT
            if meta.status != "completed" or not export.exists():
                if meta.status == "completed":
                    out.problems.append(f"{meta.id}: marcada completed pero falta {CVAT_EXPORT}")
                out.pending.append(meta)
                continue
            package = json.loads((d / PACKAGE).read_text(encoding="utf-8"))
            corrected = {r.rel_path: r for r in coco.read_dataset(export, d, manifest.id)}
            by_rel: dict[str, tuple[str | None, list[Box]]] = {}
            for flat, info in package["images"].items():
                rec = corrected.get(flat)
                if rec is None:
                    out.problems.append(f"{meta.id}: {flat} no está en la exportación de CVAT")
                    continue
                by_rel[info["rel_path"]] = (info["sha256"], rec.boxes)
            out.applied.append(_Applied(meta, by_rel))
        return out

    def apply(self, record: ImageRecord) -> None:
        for a in self.applied:
            hit = a.by_rel_path.get(record.rel_path)
            if hit is None:
                continue
            sha, boxes = hit
            if sha is not None and record.sha256 != sha:
                record.issues.append(Issue("correction_image_mismatch", Severity.ERROR,
                                           f"{a.meta.id}: la imagen no coincide con la del paquete"))
                continue
            record.boxes = [Box(**vars(b)) for b in boxes]
            record.corrections.append(a.meta.id)
