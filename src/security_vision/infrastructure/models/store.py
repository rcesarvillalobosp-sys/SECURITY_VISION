"""Registro de modelos en disco: ml/model_registry/<nombre>/<versión>/model.yaml (+ artefacto).

El YAML se versiona en git; el artefacto (.onnx) no. La integridad se garantiza con sha256.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from security_vision.core.interfaces.inference import ModelArtifact, ModelSpec


class ModelNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class RegisteredModel:
    spec: ModelSpec
    artifact: ModelArtifact
    directory: Path


class ModelStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def list(self) -> list[RegisteredModel]:
        out = []
        for yml in sorted(self.root.glob("*/*/model.yaml")):
            out.append(self._load(yml))
        return out

    def get(self, model_id: str) -> RegisteredModel:
        """``model_id`` = "nombre@versión"."""
        if "@" not in model_id:
            raise ModelNotFoundError(f"identificador de modelo inválido: {model_id!r} (use nombre@versión)")
        name, version = model_id.split("@", 1)
        yml = self.root / name / version / "model.yaml"
        if not yml.exists():
            raise ModelNotFoundError(f"modelo no registrado: {model_id}")
        return self._load(yml)

    @staticmethod
    def _load(yml: Path) -> RegisteredModel:
        spec = ModelSpec.model_validate(yaml.safe_load(yml.read_text(encoding="utf-8")))
        if f"{yml.parent.parent.name}@{yml.parent.name}" != spec.model_id:
            raise ValueError(f"{yml}: nombre/versión no coinciden con la carpeta")
        path = (yml.parent / spec.artifact).resolve()
        if not path.is_relative_to(yml.parent.resolve()):
            raise ValueError(f"{yml}: el artefacto debe estar dentro de la carpeta del modelo")
        if not path.exists():
            raise ModelNotFoundError(f"falta el artefacto {path.name} de {spec.model_id} (no se versiona: "
                                     "ejecutar el script de exportación)")
        return RegisteredModel(spec, ModelArtifact(path=path, sha256=spec.sha256), yml.parent)
