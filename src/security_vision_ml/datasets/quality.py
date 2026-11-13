"""Controles de calidad: resolución, duplicados, coherencia de etiquetas y estadísticas."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from security_vision.core.domain.taxonomy import NEGATIVE_TO_POSITIVE, CanonicalClass

from .imaging import hamming_matrix_row
from .records import ImageRecord, Issue, Severity, intersection_over_first, iou


@dataclass(frozen=True)
class QualityConfig:
    min_image_side: int = 320  # px: por debajo, resolución insuficiente
    min_box_side_px: int = 8  # px: cajas más pequeñas son poco fiables
    near_duplicate_hamming: int = 6  # pHash 64 bits
    duplicate_box_iou: float = 0.9
    contradiction_iou: float = 0.5
    max_aspect_ratio: float = 15.0
    ppe_in_person_ioa: float = 0.3


PERSON = CanonicalClass.PERSON.value


def check_resolution(rec: ImageRecord, cfg: QualityConfig) -> None:
    if rec.width is None or rec.height is None:
        return
    if min(rec.width, rec.height) < cfg.min_image_side:
        rec.issues.append(Issue("low_resolution", Severity.WARNING, f"{rec.width}x{rec.height}"))
    for i, b in enumerate(rec.boxes):
        bw, bh = b.w * rec.width, b.h * rec.height
        if 0 < min(bw, bh) < cfg.min_box_side_px:
            rec.issues.append(Issue("tiny_box", Severity.WARNING, f"{b.source_class} {bw:.0f}x{bh:.0f}px", i))


def check_labels(rec: ImageRecord, cfg: QualityConfig, source_annotates_person: bool) -> None:
    boxes = rec.boxes
    for i, a in enumerate(boxes):
        if a.w > 0 and a.h > 0 and max(a.w / a.h, a.h / a.w) > cfg.max_aspect_ratio:
            rec.issues.append(Issue("extreme_aspect_ratio", Severity.WARNING, a.source_class, i))
        for j in range(i + 1, len(boxes)):
            b = boxes[j]
            overlap = iou(a, b)
            if a.source_class == b.source_class and overlap >= cfg.duplicate_box_iou:
                detail = f"{a.source_class} IoU={overlap:.2f}"
                rec.issues.append(Issue("duplicate_box", Severity.WARNING, detail, j))
            pair = {a.canonical, b.canonical}
            for neg, pos in NEGATIVE_TO_POSITIVE.items():
                if pair == {neg.value, pos.value} and overlap >= cfg.contradiction_iou:
                    detail = f"{pos.value} vs {neg.value} IoU={overlap:.2f}"
                    rec.issues.append(Issue("contradictory_labels", Severity.WARNING, detail, j))
    if source_annotates_person:
        persons = [b for b in boxes if b.canonical == PERSON]
        for i, b in enumerate(boxes):
            if b.canonical in (None, PERSON):
                continue
            if not any(intersection_over_first(b, p) >= cfg.ppe_in_person_ioa for p in persons):
                rec.issues.append(Issue("ppe_without_person", Severity.WARNING, b.source_class, i))


@dataclass
class DuplicateReport:
    exact_groups: list[list[str]] = field(default_factory=list)
    near_pairs: list[tuple[str, str, int]] = field(default_factory=list)

    @property
    def cross_source_exact(self) -> list[list[str]]:
        return [g for g in self.exact_groups if len({k.split("::")[0] for k in g}) > 1]


def record_key(rec: ImageRecord) -> str:
    return f"{rec.source_id}::{rec.rel_path}"


def find_duplicates(records: Sequence[ImageRecord], cfg: QualityConfig) -> DuplicateReport:
    report = DuplicateReport()
    by_sha: dict[str, list[str]] = defaultdict(list)
    for r in records:
        if r.sha256:
            by_sha[r.sha256].append(record_key(r))
    report.exact_groups = [sorted(v) for v in by_sha.values() if len(v) > 1]

    hashed = [r for r in records if r.phash is not None]
    if len(hashed) > 1:
        arr = np.array([r.phash for r in hashed], dtype=np.uint64)
        for i in range(len(hashed) - 1):
            dist = hamming_matrix_row(arr, i)
            for off in np.nonzero(dist <= cfg.near_duplicate_hamming)[0]:
                j = i + 1 + int(off)
                if hashed[i].sha256 == hashed[j].sha256:
                    continue  # ya contado como exacto
                report.near_pairs.append((record_key(hashed[i]), record_key(hashed[j]), int(dist[off])))
    return report


def resolution_bucket(rec: ImageRecord) -> str:
    if rec.width is None or rec.height is None:
        return "desconocida"
    s = min(rec.width, rec.height)
    for limit, label in ((320, "<320"), (480, "320-479"), (720, "480-719"), (1080, "720-1079")):
        if s < limit:
            return label
    return ">=1080"


def box_size_bucket(rec: ImageRecord, area_norm: float) -> str:
    if rec.width is None or rec.height is None:
        return "desconocido"
    px = area_norm * rec.width * rec.height
    return "small(<32²)" if px < 32**2 else "medium(<96²)" if px < 96**2 else "large"


def compute_stats(records: Sequence[ImageRecord]) -> dict:
    canonical = Counter()
    original = Counter()
    images_per_class = Counter()
    mapping_status = Counter()
    resolutions = Counter()
    box_sizes = Counter()
    issues = Counter()
    issues_by_severity = Counter()
    splits = Counter()
    boxes_per_image = []
    for r in records:
        splits[r.original_split or "sin_split"] += 1
        resolutions[resolution_bucket(r)] += 1
        boxes_per_image.append(len(r.boxes))
        seen = set()
        for b in r.boxes:
            original[b.source_class] += 1
            mapping_status[b.mapping_status or "sin_mapear"] += 1
            if b.canonical:
                canonical[b.canonical] += 1
                seen.add(b.canonical)
            box_sizes[box_size_bucket(r, b.area)] += 1
        for c in seen:
            images_per_class[c] += 1
        for i in r.issues:
            issues[i.code] += 1
            issues_by_severity[i.severity.value] += 1
    bpi = np.array(boxes_per_image) if boxes_per_image else np.zeros(1)
    return {
        "images": len(records),
        "boxes": int(bpi.sum()),
        "splits": dict(splits),
        "objects_by_original_class": dict(original.most_common()),
        "objects_by_canonical_class": dict(canonical.most_common()),
        "images_by_canonical_class": dict(images_per_class.most_common()),
        "mapping_status": dict(mapping_status),
        "resolution_min_side": dict(resolutions),
        "box_size": dict(box_sizes),
        "boxes_per_image": {
            "mean": float(bpi.mean()), "median": float(np.median(bpi)), "max": int(bpi.max()),
            "zero": int((bpi == 0).sum()),
        },
        "issues": dict(issues.most_common()),
        "issues_by_severity": dict(issues_by_severity),
    }
