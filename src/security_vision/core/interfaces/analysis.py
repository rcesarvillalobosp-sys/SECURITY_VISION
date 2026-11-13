"""Puertos de seguimiento, asociación EPP-persona, evaluación de seguridad y pipeline completo."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping, Sequence
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


class PPEAssociator(ABC):
    @abstractmethod
    def associate(self, persons: Sequence[Track], items: Sequence[Detection]) -> dict[int, list[Detection]]:
        """track_id de persona -> EPP asociados."""


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    camera_id: str
    frame_ts: datetime
    frame_size: Size
    zones: Mapping[str, list[tuple[float, float]]] = field(default_factory=dict)
    profile_id: str | None = None


@dataclass(frozen=True, slots=True)
class Transition:
    track_id: int
    previous: str
    current: str
    at: datetime


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    persons: list[PersonCompliance]
    transitions: list[Transition]
    new_violations: list[Violation]


class SecurityEvaluator(ABC):
    @abstractmethod
    def evaluate(self, tracks: Sequence[Track], associations: Mapping[int, Sequence[Detection]],
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
    associations: dict[int, list[Detection]]
    timings_ms: dict[str, float]


class AnalysisPipeline(ABC):
    """Puerto de grano grueso: permite sustituir el pipeline entero (p. ej. DeepStream)."""

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def results(self) -> Iterator[AnalyzedFrame]: ...
