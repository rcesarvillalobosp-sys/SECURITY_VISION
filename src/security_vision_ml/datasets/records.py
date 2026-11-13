"""Representación interna, independiente del formato, de imágenes y anotaciones."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Severity(StrEnum):
    ERROR = "error"  # la anotación no es utilizable
    WARNING = "warning"  # sospechosa: revisar
    INFO = "info"


@dataclass
class Issue:
    code: str
    severity: Severity
    detail: str = ""
    box_index: int | None = None


@dataclass
class Box:
    source_class: str
    # Coordenadas normalizadas xyxy en [0,1]
    x1: float
    y1: float
    x2: float
    y2: float
    canonical: str | None = None
    mapping_status: str | None = None  # direct | needs_visual_review | excluded
    from_polygon: bool = False

    @property
    def w(self) -> float:
        return self.x2 - self.x1

    @property
    def h(self) -> float:
        return self.y2 - self.y1

    @property
    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.h)


@dataclass
class ImageRecord:
    source_id: str
    rel_path: str  # relativa a la raíz del dataset extraído
    abs_path: str
    original_split: str | None
    width: int | None = None
    height: int | None = None
    sha256: str | None = None
    phash: int | None = None
    label_path: str | None = None
    has_label_file: bool = True
    boxes: list[Box] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    group_key: str | None = None
    corrections: list[str] = field(default_factory=list)  # ids de correcciones aplicadas

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["phash"] = None if self.phash is None else f"{self.phash:016x}"
        return d

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> ImageRecord:
        d = dict(d)
        d["boxes"] = [Box(**b) for b in d.get("boxes", [])]
        d["issues"] = [Issue(**{**i, "severity": Severity(i["severity"])}) for i in d.get("issues", [])]
        if d.get("phash") is not None:
            d["phash"] = int(d["phash"], 16)
        return cls(**d)


def iou(a: Box, b: Box) -> float:
    ix = max(0.0, min(a.x2, b.x2) - max(a.x1, b.x1))
    iy = max(0.0, min(a.y2, b.y2) - max(a.y1, b.y1))
    inter = ix * iy
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


def intersection_over_first(a: Box, b: Box) -> float:
    ix = max(0.0, min(a.x2, b.x2) - max(a.x1, b.x1))
    iy = max(0.0, min(a.y2, b.y2) - max(a.y1, b.y1))
    return (ix * iy) / a.area if a.area > 0 else 0.0
