"""Análisis por cámara: detecciones -> tracks de personas -> asociación de EPP."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence

from security_vision.core.domain.geometry import Size
from security_vision.core.domain.vision import Detection
from security_vision.core.interfaces.analysis import (
    AnalyzedFrame,
    EvaluationContext,
    ObjectTracker,
    PPEAssociator,
    SecurityEvaluator,
)
from security_vision.core.interfaces.video import Frame


class CameraAnalyzer:
    """Estado por cámara (tracker propio); el asociador es sin estado y puede compartirse."""

    def __init__(self, camera_id: str, tracker: ObjectTracker, associator: PPEAssociator,
                 evaluator: SecurityEvaluator | None = None) -> None:
        self.camera_id = camera_id
        self.tracker = tracker
        self.associator = associator
        self.evaluator = evaluator  # se puede sustituir en caliente al cambiar las reglas

    def process(self, frame: Frame, detections: Sequence[Detection]) -> AnalyzedFrame:
        t0 = time.perf_counter()
        persons = self.tracker.update([d for d in detections if d.class_name == "person"], frame.captured_at)
        t1 = time.perf_counter()
        assoc = self.associator.associate(persons, [d for d in detections if d.class_name != "person"])
        t2 = time.perf_counter()
        size = Size(frame.width, frame.height)
        evaluator = self.evaluator
        evaluation = (evaluator.evaluate(persons, assoc, EvaluationContext(self.camera_id, frame.captured_at, size))
                      if evaluator is not None else None)
        t3 = time.perf_counter()
        return AnalyzedFrame(camera_id=self.camera_id, frame_id=frame.frame_id, frame_ts=frame.captured_at,
                             frame_size=size, tracks=persons, associations=assoc,
                             timings_ms={"tracking": (t1 - t0) * 1000, "association": (t2 - t1) * 1000,
                                         "evaluation": (t3 - t2) * 1000},
                             evaluation=evaluation)


TrackerFactory = Callable[[], ObjectTracker]
