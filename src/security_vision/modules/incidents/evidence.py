"""Construcción de la evidencia de un incumplimiento a partir de los fotogramas analizados.

Se generan, por orden:
- ``context``: fotogramas del inicio del periodo de ausencia (lo que el revisor necesita para
  ver que la situación fue sostenida, no un instante);
- ``frame``: el fotograma exacto de la confirmación, sin alterar (JPEG de alta calidad);
- ``annotated``: el mismo fotograma con la persona y su EPP marcados;
- ``crop``: recorte ampliado de la persona.
Cada imagen lleva las detecciones de su fotograma (requisito 4) para persistirlas.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw

from security_vision.core.domain.compliance import Violation
from security_vision.core.domain.incidents import EvidenceImage
from security_vision.core.domain.vision import Detection, Track
from security_vision.core.interfaces.analysis import AnalyzedFrame

MAX_SIDE = 1920
CROP_MARGIN = 0.25


@dataclass(frozen=True)
class FrameSnapshot:
    """Fotograma analizado retenido brevemente para poder construir la evidencia."""

    rgb: np.ndarray
    analyzed: AnalyzedFrame
    detections: tuple[Detection, ...]


def _jpeg(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _fit(img: Image.Image, max_side: int = MAX_SIDE) -> Image.Image:
    if max(img.size) > max_side:
        img = img.copy()
        img.thumbnail((max_side, max_side))
    return img


def _track_of(det: Detection, snap: FrameSnapshot) -> int | None:
    if det.class_name == "person":
        best, tid = 0.0, None
        for t in snap.analyzed.tracks:
            iou = det.bbox.iou(t.bbox)
            if iou > best:
                best, tid = iou, t.track_id
        return tid if best > 0.5 else None
    for tid, lst in snap.analyzed.associations.by_person.items():
        if any(a.item is det for a in lst):
            return tid
    return None


def _image(kind: str, img: Image.Image, snap: FrameSnapshot, quality: int, meta: dict) -> EvidenceImage:
    track_ids = {i: tid for i, d in enumerate(snap.detections) if (tid := _track_of(d, snap)) is not None}
    return EvidenceImage(kind=kind, data=_jpeg(img, quality), content_type="image/jpeg", width=img.width,
                         height=img.height, captured_at=snap.analyzed.frame_ts, frame_id=snap.analyzed.frame_id,
                         meta=meta, detections=snap.detections, track_ids=track_ids)


def _annotate(img: Image.Image, snap: FrameSnapshot, track_id: int, ppe: str) -> Image.Image:
    out = img.copy()
    d = ImageDraw.Draw(out)
    w, h = out.size
    lw = max(3, w // 300)
    for t in snap.analyzed.tracks:
        b = t.bbox
        main = t.track_id == track_id
        col = (230, 40, 40) if main else (150, 150, 150)
        d.rectangle((b.x1 * w, b.y1 * h, b.x2 * w, b.y2 * h), outline=col, width=lw if main else max(1, lw // 2))
        if main:
            d.text((b.x1 * w + 4, max(0, b.y1 * h - 16)), f"P{t.track_id} - falta: {ppe}", fill=col)
    for a in snap.analyzed.associations.by_person.get(track_id, []):
        b = a.item.bbox
        col = (230, 40, 40) if a.item.class_name.startswith("no_") else (40, 200, 90)
        d.rectangle((b.x1 * w, b.y1 * h, b.x2 * w, b.y2 * h), outline=col, width=max(2, lw - 1))
        d.text((b.x1 * w, b.y2 * h + 2), f"{a.item.class_name} {a.item.confidence:.2f}", fill=col)
    return out


def _person(snap: FrameSnapshot, track_id: int) -> Track | None:
    return next((t for t in snap.analyzed.tracks if t.track_id == track_id), None)


def build_evidence(violation: Violation, confirm: FrameSnapshot, history: Sequence[FrameSnapshot],
                   max_context: int = 2) -> tuple[EvidenceImage, ...]:
    tid = violation.track_id
    meta_base = {"track_id": tid, "ppe": violation.ppe_class, "confidence": violation.confidence}
    images: list[EvidenceImage] = []
    # Contexto: fotogramas del periodo de ausencia en los que la persona aparece
    start = violation.started_at or violation.confirmed_at
    ctx = [s for s in history if start <= s.analyzed.frame_ts < violation.confirmed_at and _person(s, tid)]
    if ctx:
        picks = [ctx[0]] if len(ctx) == 1 or max_context == 1 else [ctx[0], ctx[len(ctx) // 2]]
        for s in picks[:max_context]:
            img = _fit(Image.fromarray(s.rgb))
            images.append(_image("context", _annotate(img, s, tid, violation.ppe_class), s, 80,
                                 meta_base | {"seconds_before": (violation.confirmed_at - s.analyzed.frame_ts)
                                              .total_seconds()}))
    full = _fit(Image.fromarray(confirm.rgb))
    images.append(_image("frame", full, confirm, 92, meta_base))
    images.append(_image("annotated", _annotate(full, confirm, tid, violation.ppe_class), confirm, 85, meta_base))
    person = _person(confirm, tid)
    if person is not None:
        src = Image.fromarray(confirm.rgb)
        b = person.bbox
        mw, mh = b.width * CROP_MARGIN, b.height * CROP_MARGIN
        box = (int(max(0, b.x1 - mw) * src.width), int(max(0, b.y1 - mh) * src.height),
               int(min(1, b.x2 + mw) * src.width), int(min(1, b.y2 + mh) * src.height))
        if box[2] - box[0] >= 8 and box[3] - box[1] >= 8:
            crop = _fit(src.crop(box), 800)
            images.append(_image("crop", crop, confirm, 90, meta_base | {"crop_box_px": list(box)}))
    return tuple(images)
