"""Resultados de percepción: detecciones y tracks. Python puro, sin dependencias de visión."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from .geometry import BBox, Size


@dataclass(frozen=True, slots=True)
class Detection:
    """Una detección en un fotograma. Cubre todos los campos exigidos por el requisito 4."""

    camera_id: UUID
    frame_id: int
    frame_ts: datetime
    frame_size: Size
    class_name: str  # clase canónica (taxonomy.CanonicalClass) o clase extendida registrada
    bbox: BBox
    confidence: float
    model_id: str  # nombre@versión
    inference_ms: float
    track_id: int | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confianza fuera de [0,1]")
        if self.frame_ts.tzinfo is None:
            raise ValueError("frame_ts debe tener zona horaria (UTC)")


class TrackState(StrEnum):
    TENTATIVE = "tentative"
    CONFIRMED = "confirmed"
    LOST = "lost"


@dataclass(slots=True)
class Track:
    """Identificador temporal de un objeto entre fotogramas. No identifica a la persona."""

    track_id: int
    camera_id: UUID
    class_name: str
    bbox: BBox
    confidence: float
    state: TrackState
    first_seen: datetime
    last_seen: datetime
    hits: int = 1
    history: list[BBox] = field(default_factory=list)
