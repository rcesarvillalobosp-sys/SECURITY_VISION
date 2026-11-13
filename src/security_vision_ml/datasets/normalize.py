"""Normalización a la taxonomía canónica y creación de la copia de trabajo.

La copia de trabajo (``work/<source>/<version>/``) contiene:
- ``index.jsonl``: un registro por imagen (ruta al original, hashes, cajas con clase
  original y canónica, estado de mapeo, problemas detectados).
- ``labels/``: etiquetas YOLO normalizadas con índices canónicos, SOLO con cajas de
  mapeo directo. Las imágenes no se copian: el original es de solo lectura y la
  normalización no modifica píxeles. Cualquier transformación de imagen futura
  escribirá archivos nuevos en ``work/``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path

from security_vision.core.domain.taxonomy import CanonicalClass, class_index

from .corrections import CorrectionSet
from .imaging import inspect_image
from .records import ImageRecord, Issue, Severity
from .sources import MappingStatus, SourceManifest

INDEX_NAME = "index.jsonl"


def apply_mapping(record: ImageRecord, manifest: SourceManifest) -> None:
    for i, box in enumerate(record.boxes):
        rule = manifest.effective_mapping(box.source_class, frozenset(record.corrections))
        box.mapping_status = rule.status.value
        box.canonical = rule.target.value if rule.target is not None else None
        if box.source_class not in manifest.class_mapping:
            record.issues.append(Issue("unmapped_class", Severity.WARNING, box.source_class, i))


def usable_for_training(record: ImageRecord) -> bool:
    """Una imagen con cajas pendientes de revisión NO se usa: quitar esas cajas convertiría
    objetos reales en fondo (falsos negativos en el entrenamiento)."""
    if any(i.severity is Severity.ERROR for i in record.issues):
        return False
    return all(b.mapping_status != MappingStatus.NEEDS_VISUAL_REVIEW.value for b in record.boxes)


def canonical_yolo_lines(record: ImageRecord) -> list[str]:
    lines = []
    for b in record.boxes:
        if b.mapping_status != MappingStatus.DIRECT.value or b.canonical is None:
            continue
        x1, y1 = max(0.0, b.x1), max(0.0, b.y1)
        x2, y2 = min(1.0, b.x2), min(1.0, b.y2)
        if x2 <= x1 or y2 <= y1:
            continue
        cid = class_index(CanonicalClass(b.canonical))
        lines.append(f"{cid} {(x1 + x2) / 2:.6f} {(y1 + y2) / 2:.6f} {x2 - x1:.6f} {y2 - y1:.6f}")
    return lines


def build_working_copy(records: Iterable[ImageRecord], manifest: SourceManifest, work_dir: Path,
                       corrections: CorrectionSet | None = None) -> list[ImageRecord]:
    work_dir.mkdir(parents=True, exist_ok=True)
    labels_dir = work_dir / "labels"
    out: list[ImageRecord] = []
    with (work_dir / INDEX_NAME).open("w", encoding="utf-8") as fh:
        for rec in records:
            inspect_image(rec)
            if corrections is not None:
                corrections.apply(rec)
            apply_mapping(rec, manifest)
            lbl = labels_dir / Path(rec.rel_path).with_suffix(".txt")
            lbl.parent.mkdir(parents=True, exist_ok=True)
            lbl.write_text("\n".join(canonical_yolo_lines(rec)), encoding="utf-8")
            fh.write(json.dumps(rec.to_json(), ensure_ascii=False) + "\n")
            out.append(rec)
    return out


def load_index(work_dir: Path) -> Iterator[ImageRecord]:
    with (work_dir / INDEX_NAME).open(encoding="utf-8") as fh:
        for line in fh:
            yield ImageRecord.from_json(json.loads(line))
