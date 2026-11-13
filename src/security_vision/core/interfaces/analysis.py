"""Puertos de seguimiento, asociación EPP-persona, evaluación de seguridad y pipeline completo."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from ..domain.compliance import PersonCompliance, Violation
from ..domain.geometry import Size
from ..domain.vision import Detection, Track


class ObjectTracker(ABC):
    provider_name: ClassVar[str]

    @abstractmethod
    def update(self, detections: Sequence[Detection], frame_ts: datetime) -> list[Track]: ...

    @abstractmethod
    def reset(self) -> None: ...

    @abstractmethod
    def get_tracks(self) -> list[Track]: ...


@dataclass(frozen=True, slots=True)
class Association:
    """Un EPP (o señal "no_*") asignado a una persona en un fotograma."""

    item: Detection
    slot: str  # región corporal: head | eyes | torso | hands | feet
    score: float  # calidad geométrica de la asignación [0, 1]
    ambiguous: bool  # otra persona era casi igual de plausible (oclusión/solape)


class PPEAssociator(ABC):
    @abstractmethod
    def associate(self, persons: Sequence[Track], items: Sequence[Detection]) -> AssociationResult:
        """Asigna cada EPP a como mucho una persona, respetando la capacidad de cada región."""


@dataclass(frozen=True, slots=True)
class AssociationResult:
    by_person: dict[int, list[Association]]  # track_id -> EPP asociados
    unassigned: list[Detection]  # EPP sin persona plausible (persona no detectada, falso positivo...)


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    camera_id: str
    frame_ts: datetime
    frame_size: Size


@dataclass(frozen=True, slots=True)
class Transition:
    track_id: int
    previous: str
    current: str
    at: datetime


@dataclass(frozen=True, slots=True)
class ClosedViolation:
    violation: Violation
    closed_at: datetime
    reason: str  # "corrected" (EPP visto de nuevo de forma sostenida) | "track_lost"


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    persons: list[PersonCompliance]
    transitions: list[Transition]
    new_violations: list[Violation]
    closed_violations: list[ClosedViolation] = field(default_factory=list)


class SecurityEvaluator(ABC):
    """Evaluador con estado por cámara. Las reglas (perfiles y zonas) se inyectan al construirlo."""

    @abstractmethod
    def evaluate(self, tracks: Sequence[Track], associations: AssociationResult,
                 ctx: EvaluationContext) -> EvaluationResult: ...

    @abstractmethod
    def get_violations(self) -> list[Violation]: ...

    @abstractmethod
    def get_compliance_status(self, track_id: int | None = None) -> list[PersonCompliance]: ...


@dataclass(frozen=True, slots=True)
class AnalyzedFrame:
    camera_id: str
    frame_id: int
    frame_ts: datetime
    frame_size: Size
    tracks: list[Track]
    associations: AssociationResult
    timings_ms: dict[str, float]
    evaluation: EvaluationResult | None = None


class AnalysisPipeline(ABC):
    """Puerto de grano grueso: permite sustituir el pipeline entero (p. ej. DeepStream)."""

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def results(self) -> Iterator[AnalyzedFrame]: ...
