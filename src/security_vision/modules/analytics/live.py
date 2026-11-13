"""Datos en vivo para el dashboard: resumen compacto por fotograma analizado y agregados por minuto."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from security_vision.core.domain.compliance import ComplianceStatus
from security_vision.core.interfaces.analysis import AnalyzedFrame

STATUS_FIELD = {
    ComplianceStatus.CUMPLIMIENTO: "compliant",
    ComplianceStatus.EN_REVISION: "in_review",
    ComplianceStatus.POSIBLE_INCUMPLIMIENTO: "possible",
    ComplianceStatus.INCUMPLIMIENTO_CONFIRMADO: "confirmed",
    ComplianceStatus.NO_VERIFICABLE: "unverifiable",
}
MAX_PAYLOAD = 7500  # NOTIFY admite 8000 bytes


def _b(bbox: Any) -> list[float]:
    return [round(bbox.x1, 4), round(bbox.y1, 4), round(bbox.x2, 4), round(bbox.y2, 4)]


def live_frame_payload(af: AnalyzedFrame) -> dict[str, Any]:
    """Resumen compacto (cajas normalizadas) para superponer sobre el vídeo en el navegador."""
    status = {p.track_id: p for p in af.evaluation.persons} if af.evaluation else {}
    tracks = []
    for t in af.tracks:
        p = status.get(t.track_id)
        tracks.append({"id": t.track_id, "b": _b(t.bbox),
                       "s": p.status.value if p else None,
                       "ppe": {k: v.value for k, v in p.ppe.items()} if p else {}})
    items = [{"c": a.item.class_name, "b": _b(a.item.bbox), "p": tid, "a": a.ambiguous}
             for tid, lst in af.associations.by_person.items() for a in lst]
    items += [{"c": d.class_name, "b": _b(d.bbox), "p": None, "a": False} for d in af.associations.unassigned]
    payload = {"cam": af.camera_id, "ts": af.frame_ts.isoformat(), "fid": af.frame_id,
               "w": af.frame_size.width, "h": af.frame_size.height, "tracks": tracks, "items": items}
    # Escenas muy pobladas: se recortan los EPP antes que las personas para respetar el límite
    while len(str(payload)) > MAX_PAYLOAD and payload["items"]:
        payload["items"] = payload["items"][: len(payload["items"]) // 2]
    return payload


@dataclass
class MinuteBucket:
    analyzed_frames: int = 0
    person_frames: int = 0
    max_persons: int = 0
    counts: dict[str, int] = field(default_factory=lambda: {v: 0 for v in STATUS_FIELD.values()})


class StatsAccumulator:
    """Acumula por (cámara, minuto) desde los hilos de análisis; ``drain`` entrega y reinicia."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[tuple[str, datetime], MinuteBucket] = {}

    def add(self, af: AnalyzedFrame) -> None:
        bucket = af.frame_ts.replace(second=0, microsecond=0)
        n = len(af.tracks)
        with self._lock:
            b = self._data.setdefault((af.camera_id, bucket), MinuteBucket())
            b.analyzed_frames += 1
            b.person_frames += n
            b.max_persons = max(b.max_persons, n)
            if af.evaluation:
                for p in af.evaluation.persons:
                    b.counts[STATUS_FIELD[p.status]] += 1

    def drain(self) -> list[dict[str, Any]]:
        """Filas listas para persistir (suma aditiva por (cámara, minuto))."""
        with self._lock:
            data, self._data = self._data, {}
        return [{"camera_id": cam, "bucket": bucket, "analyzed_frames": b.analyzed_frames,
                 "person_frames": b.person_frames, "max_persons": b.max_persons, **b.counts}
                for (cam, bucket), b in data.items()]
