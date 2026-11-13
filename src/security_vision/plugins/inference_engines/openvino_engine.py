"""Motor OpenVINO nativo (CPU Intel y GPU integrada Intel)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

import numpy as np

from security_vision.core.interfaces.inference import (
    DeviceInfo,
    DeviceRequest,
    EngineMetrics,
    InferenceEngine,
    ModelArtifact,
)

from .common import LatencyRecorder, verify_artifact


def resolve_device(core: Any, kind: str) -> str | None:
    """Traduce el tipo pedido a un dispositivo OpenVINO concreto.

    openvino-cpu | cpu -> CPU; openvino-igpu -> GPU integrada; openvino-dgpu -> GPU discreta;
    openvino-gpu -> la GPU por defecto de OpenVINO (GPU.0); openvino-gpu.N -> GPU.N.
    """
    avail = list(core.available_devices)
    if kind in ("openvino-cpu", "cpu"):
        return "CPU" if "CPU" in avail else None
    gpus = [d for d in avail if d.startswith("GPU")]
    if kind == "openvino-gpu":
        return "GPU.0" if "GPU.0" in gpus else ("GPU" if "GPU" in gpus else None)
    if kind.startswith("openvino-gpu."):
        dev = "GPU." + kind.rsplit(".", 1)[1]
        return dev if dev in gpus else None
    wanted = {"openvino-igpu": "INTEGRATED", "openvino-dgpu": "DISCRETE"}.get(kind)
    if wanted:
        for d in gpus:
            if str(core.get_property(d, "DEVICE_TYPE")).endswith(wanted):
                return d
    return None


class OpenVinoEngine(InferenceEngine):
    provider_name: ClassVar[str] = "openvino"

    def __init__(self, performance_hint: str = "LATENCY") -> None:
        self._compiled: Any = None
        self._request: Any = None
        self._device: DeviceInfo | None = None
        self._latency = LatencyRecorder()
        self._hint = performance_hint

    @staticmethod
    def _core() -> Any:
        import openvino as ov

        return ov.Core()

    @classmethod
    def available_devices(cls) -> list[DeviceInfo]:
        core = cls._core()
        out = []
        for dev in core.available_devices:
            if dev == "CPU":
                kind = "openvino-cpu"
            elif dev.startswith("GPU"):
                integrated = str(core.get_property(dev, "DEVICE_TYPE")).endswith("INTEGRATED")
                kind = "openvino-igpu" if integrated else "openvino-dgpu"
            else:
                kind = f"openvino-{dev.lower()}"
            out.append(DeviceInfo(kind=kind, name=core.get_property(dev, "FULL_DEVICE_NAME")))
        return out

    def load_model(self, artifact: ModelArtifact, device: DeviceRequest) -> None:
        core = self._core()
        path = verify_artifact(artifact)
        errors = []
        for kind in device.preference:
            ov_dev = resolve_device(core, kind)
            if ov_dev is None:
                errors.append(f"{kind}: no disponible")
                continue
            try:
                model = core.read_model(str(path))
                self._compiled = core.compile_model(model, ov_dev, {"PERFORMANCE_HINT": self._hint})
            except Exception as exc:
                errors.append(f"{kind}: {type(exc).__name__}: {str(exc)[:200]}")
                continue
            self._request = self._compiled.create_infer_request()
            self._device = DeviceInfo(kind=kind if kind != "cpu" else "openvino-cpu",
                                      name=core.get_property(ov_dev, "FULL_DEVICE_NAME"))
            return
        raise RuntimeError("ningún dispositivo OpenVINO disponible: " + "; ".join(errors))

    def predict(self, inputs: Mapping[str, np.ndarray]) -> dict[str, np.ndarray]:
        if self._request is None:
            raise RuntimeError("modelo no cargado")
        with self._latency.time():
            res = self._request.infer(dict(inputs))
        return {next(iter(port.get_names())): np.asarray(val) for port, val in res.items()}

    def get_device(self) -> DeviceInfo:
        if self._device is None:
            raise RuntimeError("modelo no cargado")
        return self._device

    def get_metrics(self) -> EngineMetrics:
        return self._latency.metrics(self._device)

    def unload_model(self) -> None:
        self._compiled = self._request = None
        self._device = None
