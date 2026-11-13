"""Lector COCO (formato de exportación "COCO 1.0" de CVAT)."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

from ..records import Box, ImageRecord, Issue, Severity


def read_dataset(annotations_json: Path, images_root: Path, source_id: str, split: str | None = None
                 ) -> Iterator[ImageRecord]:
    data = json.loads(annotations_json.read_text(encoding="utf-8"))
    categories = {c["id"]: c["name"] for c in data.get("categories", [])}
    anns_by_image: dict[int, list[dict]] = defaultdict(list)
    for ann in data.get("annotations", []):
        anns_by_image[ann["image_id"]].append(ann)

    for img in data.get("images", []):
        path = images_root / img["file_name"]
        rec = ImageRecord(
            source_id=source_id,
            rel_path=Path(img["file_name"]).as_posix(),
            abs_path=str(path),
            original_split=split,
            width=img.get("width"),
            height=img.get("height"),
            label_path=str(annotations_json),
        )
        w, h = img.get("width") or 0, img.get("height") or 0
        for ann in anns_by_image.get(img["id"], []):
            name = categories.get(ann["category_id"])
            if name is None:
                rec.issues.append(Issue("unknown_class_id", Severity.ERROR, str(ann["category_id"])))
                continue
            if not w or not h:
                rec.issues.append(Issue("missing_image_size", Severity.ERROR, img["file_name"]))
                break
            x, y, bw, bh = ann["bbox"]
            box = Box(name, x / w, y / h, (x + bw) / w, (y + bh) / h)
            if bw <= 0 or bh <= 0:
                rec.issues.append(Issue("degenerate_box", Severity.ERROR, "", len(rec.boxes)))
            rec.boxes.append(box)
        yield rec
