"""Lector de datasets en formato YOLO (detección y, de forma tolerante, segmentación).

No modifica nada: solo lee y reporta problemas como ``Issue``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import yaml

from ..records import Box, ImageRecord, Issue, Severity

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
SPLIT_ALIASES = {"train": "train", "val": "val", "valid": "val", "validation": "val", "test": "test"}
COORD_TOL = 1e-3


def find_class_names(root: Path) -> dict[int, str]:
    """Busca un YAML con ``names`` (lista o dict) en la raíz del dataset."""
    candidates = sorted(root.rglob("*.yaml")) + sorted(root.rglob("*.yml"))
    for path in candidates:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, UnicodeDecodeError):
            continue
        if isinstance(data, dict) and "names" in data:
            names = data["names"]
            if isinstance(names, list):
                return dict(enumerate(str(n) for n in names))
            if isinstance(names, dict):
                return {int(k): str(v) for k, v in names.items()}
    raise FileNotFoundError(f"no se encontró un YAML con 'names' bajo {root}")


def _split_of(rel: Path) -> str | None:
    for part in rel.parts:
        if part.lower() in SPLIT_ALIASES:
            return SPLIT_ALIASES[part.lower()]
    return None


def label_path_for(image: Path) -> Path:
    parts = list(image.parts)
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] == "images":
            parts[i] = "labels"
            break
    return Path(*parts).with_suffix(".txt")


def parse_label_file(path: Path, names: dict[int, str]) -> tuple[list[Box], list[Issue]]:
    boxes: list[Box] = []
    issues: list[Issue] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        try:
            cls_id = int(float(parts[0]))
            values = [float(v) for v in parts[1:]]
        except (ValueError, IndexError):
            issues.append(Issue("malformed_line", Severity.ERROR, f"línea {lineno}: {line[:60]!r}"))
            continue
        if cls_id not in names:
            issues.append(Issue("unknown_class_id", Severity.ERROR, f"línea {lineno}: clase {cls_id}"))
            continue
        polygon = False
        if len(values) == 4:
            cx, cy, w, h = values
            x1, y1, x2, y2 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
        elif len(values) >= 6 and len(values) % 2 == 0:
            xs, ys = values[0::2], values[1::2]
            x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
            polygon = True
        else:
            issues.append(Issue("malformed_line", Severity.ERROR, f"línea {lineno}: {len(values)} valores"))
            continue
        box = Box(names[cls_id], x1, y1, x2, y2, from_polygon=polygon)
        idx = len(boxes)
        if min(x1, y1) < -COORD_TOL or max(x2, y2) > 1 + COORD_TOL:
            issues.append(Issue("out_of_bounds", Severity.WARNING, f"línea {lineno}", idx))
        if box.w <= 0 or box.h <= 0:
            issues.append(Issue("degenerate_box", Severity.ERROR, f"línea {lineno}", idx))
        boxes.append(box)
    return boxes, issues


def read_dataset(root: Path, source_id: str) -> Iterator[ImageRecord]:
    names = find_class_names(root)
    image_paths = sorted(p for p in root.rglob("*") if p.suffix.lower() in IMAGE_EXTS and p.is_file())
    for img in image_paths:
        rel = img.relative_to(root)
        record = ImageRecord(
            source_id=source_id,
            rel_path=rel.as_posix(),
            abs_path=str(img),
            original_split=_split_of(rel),
        )
        lbl = label_path_for(img)
        record.label_path = str(lbl)
        if lbl.exists():
            record.boxes, record.issues = parse_label_file(lbl, names)
        else:
            record.has_label_file = False
            record.issues.append(Issue("missing_label_file", Severity.WARNING, "¿imagen de fondo o etiqueta perdida?"))
        yield record


def find_orphan_labels(root: Path) -> list[str]:
    images = {
        label_path_for(p).resolve()
        for p in root.rglob("*")
        if p.suffix.lower() in IMAGE_EXTS and p.is_file()
    }
    orphans = []
    for lbl in root.rglob("*.txt"):
        if "labels" in lbl.parts and lbl.resolve() not in images:
            orphans.append(lbl.relative_to(root).as_posix())
    return sorted(orphans)
