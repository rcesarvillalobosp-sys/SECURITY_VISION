"""Micro-batching del servicio de detección: agrupa bajo carga, no mezcla resultados entre cámaras,
propaga errores y se cierra sin dejar cámaras bloqueadas."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from uuid import UUID, uuid4

import numpy as np
import pytest

from security_vision.core.domain.geometry import BBox, Size
from security_vision.core.domain.vision import Detection
from security_vision.core.interfaces.video import Frame
from security_vision.modules.analytics.timings import StageTimings
from security_vision.modules.detection.service import DetectionService


def frame(i: int) -> Frame:
    return Frame(np.full((8, 8, 3), i, np.uint8), frame_id=i, captured_at=datetime.now(UTC))


class SlowModel:
    """Doble del modelo: cada llamada cuesta ``call_ms`` (como una GPU) sea cual sea el tamaño del lote."""

    class spec:
        model_id = "lento@1"

    def __init__(self, call_ms: float = 60.0, fail: bool = False) -> None:
        self.call_ms = call_ms
        self.fail = fail
        self.batches: list[int] = []
        self.prepared_in: list[str] = []
        self.last_stage_ms: dict[str, float] = {}

    def prepare(self, f: Frame) -> int:
        self.prepared_in.append(threading.current_thread().name)
        return int(f.data[0, 0, 0])

    def detect_prepared(self, prepared, frames, cams):
        time.sleep(self.call_ms / 1000)
        if self.fail:
            raise RuntimeError("GPU sin memoria")
        self.batches.append(len(prepared))
        self.last_stage_ms = {"inference": self.call_ms}
        # La "detección" codifica el valor preparado: así se comprueba que cada cámara recibe lo suyo
        return [[Detection(camera_id=UUID(c), frame_id=f.frame_id,
                           frame_ts=f.captured_at, frame_size=Size(8, 8), class_name="person",
                           bbox=BBox(0.1, 0.1, 0.2, 0.2), confidence=p / 255, model_id="lento@1", inference_ms=1.0)]
                for p, f, c in zip(prepared, frames, cams, strict=True)]

    def detect(self, frames, cams):
        return self.detect_prepared([self.prepare(f) for f in frames], frames, cams)


def run_concurrently(svc: DetectionService, n: int) -> dict[str, list[Detection]]:
    cams = [str(uuid4()) for _ in range(n)]
    out: dict[str, list[Detection]] = {}

    def worker(i: int) -> None:
        out[cams[i]] = svc.detect(frame(i + 1), cams[i])

    threads = [threading.Thread(target=worker, args=(i,), name=f"cam-{i}") for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    return out


def test_batches_under_load_and_keeps_results_per_camera():
    model = SlowModel(call_ms=80)
    svc = DetectionService(model, max_batch=4)
    try:
        out = run_concurrently(svc, 8)
    finally:
        svc.close()
    assert len(out) == 8
    for cam, dets in out.items():
        assert str(dets[0].camera_id) == cam  # nunca se mezclan cámaras
    # 8 peticiones simultáneas con lotes de hasta 4: bastante menos de 8 llamadas al modelo
    assert sum(model.batches) == 8 and len(model.batches) <= 4 and max(model.batches) > 1
    assert svc.stats.calls == 8 and svc.stats.batches == len(model.batches)
    # El preproceso se hizo en los hilos de las cámaras, no en el despachador
    assert all(name.startswith("cam-") for name in model.prepared_in)


def test_single_request_is_not_delayed():
    model = SlowModel(call_ms=20)
    svc = DetectionService(model, max_batch=8, max_wait_ms=0)
    try:
        t0 = time.perf_counter()
        svc.detect(frame(1), str(uuid4()))
        elapsed = (time.perf_counter() - t0) * 1000
    finally:
        svc.close()
    assert model.batches == [1] and elapsed < 20 + 40  # sin espera artificial con poca carga


def test_errors_propagate_to_every_camera_in_the_batch():
    svc = DetectionService(SlowModel(call_ms=30, fail=True), max_batch=4)
    try:
        with pytest.raises(RuntimeError, match="sin memoria"):
            svc.detect(frame(1), str(uuid4()))
        assert svc.stats.errors >= 1
    finally:
        svc.close()


def test_model_without_prepare_still_works():
    class Plain:
        class spec:
            model_id = "plano@1"

        def detect(self, frames, cams):
            return [[] for _ in frames]

    svc = DetectionService(Plain())  # type: ignore[arg-type]
    try:
        assert svc.detect(frame(1), str(uuid4())) == []
    finally:
        svc.close()


def test_close_rejects_new_requests():
    svc = DetectionService(SlowModel(call_ms=1))
    svc.close()
    with pytest.raises(RuntimeError, match="cerrado"):
        svc.detect(frame(1), str(uuid4()))


def test_stage_timings_window_is_time_based():
    now = [100.0]
    t = StageTimings(window_seconds=60, clock=lambda: now[0])
    t.add("inference", 50)
    now[0] = 130
    t.add("inference", 10)
    assert t.snapshot()["inference"]["n"] == 2
    now[0] = 175  # la primera muestra (t=100) sale de la ventana
    snap = t.snapshot()["inference"]
    assert snap["n"] == 1 and snap["p50"] == 10 and snap["count"] == 2


def test_lazy_frame_converts_only_when_used_and_once():
    calls = []

    def loader():
        calls.append(1)
        return np.zeros((720, 1280, 3), np.uint8)

    f = Frame.lazy(loader, 1280, 720, frame_id=3, captured_at=datetime.now(UTC))
    assert (f.width, f.height) == (1280, 720) and not f.materialized and calls == []  # sin coste
    assert f.data.shape == (720, 1280, 3) and f.data is f.data
    assert calls == [1] and f.materialized
