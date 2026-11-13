"""Administración del modelo de detección: catálogo del registro y modelo activo (cambio en caliente).

- ``detection.active_model``: modelo elegido por la administración (prevalece sobre SV_DETECTION_MODEL).
- ``detection.loaded_model``: lo que el worker tiene cargado DE VERDAD (lo escribe el worker al cargar),
  para que la interfaz no confunda "pedido" con "en uso".
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from security_vision.core.domain.errors import NotFoundError, ValidationError
from security_vision.core.domain.identity import Principal
from security_vision.core.events.catalog import DetectionModelChanged
from security_vision.core.interfaces.inference import ModelCatalog, ModelInfo
from security_vision.core.interfaces.repositories import UnitOfWork

ACTIVE_KEY = "detection.active_model"
LOADED_KEY = "detection.loaded_model"


class ModelService:
    def __init__(self, uow: Callable[[], UnitOfWork], catalog: ModelCatalog, default_model: str | None) -> None:
        self._uow = uow
        self.catalog = catalog
        self.default_model = default_model

    async def state(self) -> tuple[list[ModelInfo], str | None, dict[str, Any] | None]:
        async with self._uow() as uow:
            active = await uow.settings.get(ACTIVE_KEY)
            loaded = await uow.settings.get(LOADED_KEY)
        active_id = (active or {}).get("model_id") or self.default_model
        return self.catalog.list(), active_id, loaded

    async def activate(self, model_id: str, *, actor: Principal, ip: str | None = None) -> ModelInfo:
        info = self.catalog.get(model_id)
        if info is None:
            raise NotFoundError("modelo no registrado")
        if not info.artifact_present or info.spec is None:
            raise ValidationError(f"el modelo no se puede activar: {info.error}")
        async with self._uow() as uow:
            prev = await uow.settings.get(ACTIVE_KEY)
            await uow.settings.set(ACTIVE_KEY, {"model_id": model_id}, actor_id=actor.user_id)
            await uow.audit.record("models.activated", actor_id=actor.user_id, entity_type="detection_model",
                                   entity_id=model_id,
                                   before={"model_id": (prev or {}).get("model_id") or self.default_model},
                                   after={"model_id": model_id}, ip=ip)
            await uow.incidents.enqueue_event(DetectionModelChanged(model_id=model_id))
            await uow.commit()
        return info
