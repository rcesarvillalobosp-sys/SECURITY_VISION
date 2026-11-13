"""Integración detección <-> worker con un detector falso (sin motores de inferencia)."""

from __future__ import annotations

import time
from uuid import UUID

import numpy as np
from security_vision_worker.runtime import AnalysisLoop, encode_annotated_jpeg

from security_vision.core.domain.geometry import BBox, Size
from security_vision.core.domain.vision import Detection
from security_vision.core.interfaces.video import Frame, VideoSourceConfig
from security_vision.modules.cameras.supervisor import CameraSpec, CameraSupervisor
from security_vision.plugins.video_sources.test_pattern import TestPatternSource

CAM = "01890000-0000-7000-8000-000000000001"


def _det(frame: Frame, cls: str) -> Detection:
    return Detection(camera_id=UUID(CAM), frame_id=frame.frame_id, frame_ts=frame.captured_at,
                     frame_size=Size(frame.width, frame.height), class_name=cls, bbox=BBox(0.1, 0.1, 0.5, 0.9),
                     confidence=0.9, model_id="fake@1", inference_ms=1.0)


def test_analysis_loop_runs_detector_at_analysis_rate():
    seen: list[list[Detection]] = []
    sup = CameraSupervisor(lambda spec: TestPatternSource(spec.source))
    try:
        w = sup.start(CameraSpec(CAM, "c", "testpattern", VideoSourceConfig(uri="testpattern://?width=64&height=48&fps=60"),
                                 analysis_fps=5))
        loop = AnalysisLoop(w, lambda f: seen.append([_det(f, "person")]))
        loop.start()
        time.sleep(1.2)
        loop.stop()
    finally:
        sup.stop_all()
    assert 4 <= len(seen) <= 8  # ~5/s durante ~1,2 s, aunque la cámara entregue 60 fps
    ids = [s[0].frame_id for s in seen]
    assert ids == sorted(set(ids))  # nunca analiza dos veces el mismo fotograma


def test_annotated_snapshot_is_valid_jpeg():
    f = Frame(np.zeros((240, 320, 3), np.uint8), frame_id=1, captured_at=__import__("datetime").datetime.now(
        __import__("datetime").UTC))
    jpeg = encode_annotated_jpeg(f.data, [_det(f, "person"), _det(f, "no_helmet")])
    assert jpeg[:2] == b"\xff\xd8" and len(jpeg) > 500
    from io import BytesIO

    from PIL import Image

    img = np.asarray(Image.open(BytesIO(jpeg)))
    assert img[:, :, 0].max() > 150  # el recuadro rojo de "no_helmet" está dibujado
