"""Puertos de inferencia (motor) y de detección (modelo). Están separados a propósito:
el modelo define pre/post-proceso y clases; el motor solo ejecuta tensores."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
from pydantic import BaseModel, ConfigDict

from ..domain.vision import Detection
from .video import Frame


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    kind: str  # "cpu", "cuda", "tensorrt", "openvino-cpu", "openvino-gpu", ...
    name: str
    memory_mb: int | None = None


class DeviceRequest(BaseModel):
    """Lista de preferencia con *fallback* explícito, p. ej. ["tensorrt", "cuda", "cpu"]."""

    model_config = ConfigDict(extra="forbid")
    preference: list[str] = ["cpu"]
    device_index: int = 0
    allow_fallback: bool = True


@dataclass(frozen=True, slots=True)
class ModelArtifact:
    path: Path
    sha256: str
    format: str = "onnx"


@dataclass(frozen=True, slots=True)
class EngineMetrics:
    calls: int
    p50_ms: float | None
    p95_ms: float | None
    device: DeviceInfo | None


class InferenceEngine(ABC):
    provider_name: ClassVar[str]

    @classmethod
    @abstractmethod
    def available_devices(cls) -> list[DeviceInfo]: ...

    @abstractmethod
    def load_model(self, artifact: ModelArtifact, device: DeviceRequest) -> None: ...

    @abstractmethod
    def predict(self, inputs: Mapping[str, np.ndarray]) -> dict[str, np.ndarray]: ...

    @abstractmethod
    def get_device(self) -> DeviceInfo: ...

    @abstractmethod
    def get_metrics(self) -> EngineMetrics: ...

    @abstractmethod
    def unload_model(self) -> None: ...


class ModelSpec(BaseModel):
    """Contenido de ``model.yaml`` en el registro de modelos (ml/model_registry/<nombre>/<versión>/)."""

    model_config = ConfigDict(extra="forbid")
    name: str
    version: str
    architecture: str  # "rtdetr", "rfdetr", ... (adaptador DetectionModel registrado)
    artifact: str  # ruta relativa al model.yaml
    sha256: str
    input_size: tuple[int, int]  # (alto, ancho)
    labels: list[str]  # índice de salida del modelo -> etiqueta del modelo
    class_map: dict[str, str]  # etiqueta del modelo -> clase canónica (las no mapeadas se ignoran)
    score_threshold: float = 0.3
    class_thresholds: dict[str, float] = {}  # umbral por clase canónica
    params: dict[str, Any] = {}  # parámetros específicos del adaptador (normalización, nombres de E/S...)
    license: str
    weights_license: str
    weights_source: str
    dataset_ref: str | None = None
    notes: str | None = None

    @property
    def model_id(self) -> str:
        return f"{self.name}@{self.version}"


class DetectionModel(ABC):
    architecture: ClassVar[str]

    def __init__(self, spec: ModelSpec, engine: InferenceEngine) -> None:
        self.spec = spec
        self.engine = engine

    @abstractmethod
    def detect(self, frames: Sequence[Frame], camera_ids: Sequence[str]) -> list[list[Detection]]: ...

    def classes(self) -> dict[str, str]:
        return dict(self.spec.class_map)

    def warmup(self) -> None:  # noqa: B027 - opcional para los adaptadores
        """Ejecución en vacío para estabilizar latencias (opcional)."""
