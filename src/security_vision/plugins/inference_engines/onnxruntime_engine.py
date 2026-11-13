"""Motor ONNX Runtime: CPU, CUDA y TensorRT (y OpenVINO EP si la compilación lo incluye).

La lista de preferencia se recorre en orden; si ONNX Runtime cae silenciosamente a otro
proveedor (p. ej. faltan DLL de CUDA), se detecta comprobando ``session.get_providers()`` y se
registra en el log en vez de fingir que se usa la GPU.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path
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

log = logging.getLogger(__name__)
PROVIDERS = {
    "tensorrt": "TensorrtExecutionProvider",
    "cuda": "CUDAExecutionProvider",
    "openvino": "OpenVINOExecutionProvider",
    "directml": "DmlExecutionProvider",
    "cpu": "CPUExecutionProvider",
}
_DLLS_LOADED = False


def _ort() -> Any:
    global _DLLS_LOADED
    import onnxruntime as ort

    if not _DLLS_LOADED and hasattr(ort, "preload_dlls"):
        # Carga las DLL de CUDA/cuDNN instaladas como paquetes pip (nvidia-*) si existen.
        try:
            ort.preload_dlls(directory="")
        except Exception as exc:
            log.debug("preload_dlls: %s", exc)
        _DLLS_LOADED = True
    return ort


def _gpu_name() -> tuple[str, int | None]:
    try:
        import pynvml  # type: ignore[import-not-found]

        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        return pynvml.nvmlDeviceGetName(h), int(pynvml.nvmlDeviceGetMemoryInfo(h).total / 2**20)
    except Exception:
        return "GPU NVIDIA", None


class OnnxRuntimeEngine(InferenceEngine):
    provider_name: ClassVar[str] = "onnxruntime"

    def __init__(self, intra_op_threads: int | None = None, cache_dir: str | None = None) -> None:
        self._session: Any = None
        self._device: DeviceInfo | None = None
        self._latency = LatencyRecorder()
        self._threads = intra_op_threads
        self._cache_dir = cache_dir or os.path.join("var", "trt_cache")

    @classmethod
    def available_devices(cls) -> list[DeviceInfo]:
        ort = _ort()
        avail = set(ort.get_available_providers())
        return [DeviceInfo(kind=k, name=v) for k, v in PROVIDERS.items() if v in avail]

    def _provider_entry(self, kind: str) -> Any:
        name = PROVIDERS[kind]
        if kind == "tensorrt":
            Path(self._cache_dir).mkdir(parents=True, exist_ok=True)
            return (name, {"trt_fp16_enable": True, "trt_engine_cache_enable": True,
                           "trt_engine_cache_path": self._cache_dir, "trt_timing_cache_enable": True})
        if kind == "cuda":
            return (name, {"cudnn_conv_algo_search": "HEURISTIC"})
        return name

    def load_model(self, artifact: ModelArtifact, device: DeviceRequest) -> None:
        ort = _ort()
        path = verify_artifact(artifact)
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.log_severity_level = 3  # solo errores: los avisos de ORT (ScatterND...) se repiten en cada inferencia
        if self._threads:
            opts.intra_op_num_threads = self._threads
        avail = set(ort.get_available_providers())
        errors: list[str] = []
        for kind in device.preference:
            if kind not in PROVIDERS or PROVIDERS[kind] not in avail:
                errors.append(f"{kind}: no disponible en esta instalación")
                continue
            providers = [self._provider_entry(kind)]
            if kind == "tensorrt":
                providers.append(self._provider_entry("cuda"))  # nodos no soportados por TRT
            if kind != "cpu":
                providers.append("CPUExecutionProvider")
            try:
                session = ort.InferenceSession(str(path), sess_options=opts, providers=providers)
            except Exception as exc:
                errors.append(f"{kind}: {type(exc).__name__}: {str(exc)[:200]}")
                continue
            active = session.get_providers()[0]
            if active != PROVIDERS[kind]:
                errors.append(f"{kind}: ONNX Runtime usó {active} en su lugar")
                continue
            self._session = session
            if kind in ("cuda", "tensorrt"):
                name, mem = _gpu_name()
                self._device = DeviceInfo(kind=kind, name=name, memory_mb=mem)
            else:
                self._device = DeviceInfo(kind=kind, name=PROVIDERS[kind])
            if errors:
                log.warning("dispositivo de respaldo %s; descartados: %s", kind, "; ".join(errors))
            return
            # (no se alcanza)
        raise RuntimeError("ningún dispositivo solicitado está disponible: " + "; ".join(errors))

    def input_names(self) -> list[str]:
        return [i.name for i in self._session.get_inputs()]

    def predict(self, inputs: Mapping[str, np.ndarray]) -> dict[str, np.ndarray]:
        if self._session is None:
            raise RuntimeError("modelo no cargado")
        with self._latency.time():
            outputs = self._session.run(None, dict(inputs))
        names = [o.name for o in self._session.get_outputs()]
        return dict(zip(names, outputs, strict=True))

    def get_device(self) -> DeviceInfo:
        if self._device is None:
            raise RuntimeError("modelo no cargado")
        return self._device

    def get_metrics(self) -> EngineMetrics:
        return self._latency.metrics(self._device)

    def unload_model(self) -> None:
        self._session = None
        self._device = None
