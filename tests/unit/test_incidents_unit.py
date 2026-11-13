from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from uuid import UUID

import numpy as np
from PIL import Image

from security_vision.core.domain.compliance import Violation
from security_vision.core.domain.geometry import BBox, Size
from security_vision.core.domain.incidents import ALLOWED_TRANSITIONS, violation_event_id
from security_vision.core.domain.incidents import IncidentStatus as S
from security_vision.core.domain.vision import Detection, Track, TrackState
from security_vision.core.interfaces.analysis import AnalyzedFrame, Association, AssociationResult
from security_vision.modules.incidents.evidence import FrameSnapshot, build_evidence

CAM = "01890000-0000-7000-8000-000000000001"
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def snap(k: int) -> FrameSnapshot:
    ts = T0 + timedelta(seconds=k)
    rgb = np.full((720, 1280, 3), 40 + k, np.uint8)
    p = Track(7, UUID(CAM), "person", BBox(0.4, 0.2, 0.5, 0.9), 0.9, TrackState.CONFIRMED, T0, ts)
    nh = Detection(UUID(CAM), k, ts, Size(1280, 720), "no_helmet", BBox(0.42, 0.18, 0.48, 0.28), 0.8, "m@1", 30.0)
    pd = Detection(UUID(CAM), k, ts, Size(1280, 720), "person", BBox(0.4, 0.2, 0.5, 0.9), 0.9, "m@1", 30.0)
    af = AnalyzedFrame(CAM, k, ts, Size(1280, 720), [p], AssociationResult({7: [Association(nh, "head", 0.9, False)]},
                                                                            []), {})
    return FrameSnapshot(rgb, af, (pd, nh))


def test_evidence_contains_context_frame_annotated_and_crop_with_detections():
    hist = [snap(k) for k in range(8)]
    v = Violation(CAM, 7, "helmet", T0 + timedelta(seconds=8), 0.9, started_at=T0 + timedelta(seconds=2))
    imgs = build_evidence(v, snap(8), hist)
    kinds = [i.kind for i in imgs]
    assert kinds == ["context", "context", "frame", "annotated", "crop"]
    ctx = [i for i in imgs if i.kind == "context"]
    assert ctx[0].captured_at == T0 + timedelta(seconds=2)  # inicio del periodo de ausencia
    assert ctx[0].meta["seconds_before"] == 6.0
    frame = next(i for i in imgs if i.kind == "frame")
    assert Image.open(io.BytesIO(frame.data)).size == (1280, 720) and frame.frame_id == 8
    crop = next(i for i in imgs if i.kind == "crop")
    assert crop.width < 1280 and crop.height < 720
    # Detecciones del fotograma con su track: persona por IoU, EPP por asociación
    assert frame.track_ids == {0: 7, 1: 7} and {d.class_name for d in frame.detections} == {"person", "no_helmet"}


def test_evidence_without_history_still_has_confirmation_frames():
    v = Violation(CAM, 7, "helmet", T0, 0.9, started_at=T0)
    assert [i.kind for i in build_evidence(v, snap(0), [])] == ["frame", "annotated", "crop"]


def test_review_transitions():
    assert S.RESUELTO not in ALLOWED_TRANSITIONS[S.PENDIENTE]  # no se resuelve sin confirmar
    assert S.CONFIRMADO in ALLOWED_TRANSITIONS[S.PENDIENTE]
    assert all(S.EN_REVISION in ALLOWED_TRANSITIONS[s] for s in (S.CONFIRMADO, S.DESCARTADO, S.RESUELTO))


def test_violation_event_id_is_deterministic():
    v = Violation(CAM, 7, "helmet", T0, 0.9)
    assert violation_event_id(v) == violation_event_id(Violation(CAM, 7, "helmet", T0, 0.5))
    assert violation_event_id(v) != violation_event_id(Violation(CAM, 8, "helmet", T0, 0.9))
