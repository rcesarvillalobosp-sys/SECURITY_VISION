"""Registro de proveedores intercambiables (fuentes de vídeo, motores, modelos, trackers...).

Los proveedores se registran explícitamente o se descubren mediante *entry points*
(``security_vision.<grupo>``), de modo que un plugin de terceros puede instalarse como
paquete independiente sin modificar el núcleo.
"""

from __future__ import annotations

from collections.abc import Callable
from importlib.metadata import entry_points
from typing import Any, TypeVar

T = TypeVar("T")

ENTRY_POINT_GROUPS: dict[str, str] = {
    "VideoSource": "security_vision.video_sources",
    "InferenceEngine": "security_vision.inference_engines",
    "DetectionModel": "security_vision.detection_models",
    "ObjectTracker": "security_vision.trackers",
    "AlertChannel": "security_vision.alert_channels",
}


class ProviderNotFoundError(LookupError):
    pass


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[type, dict[str, type]] = {}

    def register(self, port: type[T], name: str, implementation: type[T]) -> None:
        if not issubclass(implementation, port):
            raise TypeError(f"{implementation.__name__} no implementa {port.__name__}")
        bucket = self._providers.setdefault(port, {})
        if name in bucket and bucket[name] is not implementation:
            raise ValueError(f"proveedor {name!r} ya registrado para {port.__name__}")
        bucket[name] = implementation

    def provider(self, port: type[T], name: str) -> Callable[..., T]:
        try:
            return self._providers[port][name]
        except KeyError:
            available = ", ".join(sorted(self._providers.get(port, {}))) or "ninguno"
            raise ProviderNotFoundError(
                f"no hay proveedor {name!r} para {port.__name__} (disponibles: {available})"
            ) from None

    def create(self, port: type[T], name: str, *args: Any, **kwargs: Any) -> T:
        return self.provider(port, name)(*args, **kwargs)

    def names(self, port: type) -> list[str]:
        return sorted(self._providers.get(port, {}))

    def discover(self, port: type) -> list[str]:
        """Carga proveedores declarados como entry points para ``port``. Devuelve los nombres cargados."""
        group = ENTRY_POINT_GROUPS.get(port.__name__)
        if group is None:
            return []
        loaded = []
        for ep in entry_points(group=group):
            self.register(port, ep.name, ep.load())
            loaded.append(ep.name)
        return loaded
