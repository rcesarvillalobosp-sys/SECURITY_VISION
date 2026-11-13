"""ByteTrack (Zhang et al., 2022; algoritmo publicado bajo MIT), implementación propia en NumPy/SciPy.

Diferencias respecto a la referencia, por el contexto de videovigilancia a baja frecuencia de análisis:
- La vida de un track perdido se mide en **segundos** (``max_lost_seconds``), no en fotogramas,
  porque cada cámara analiza a su propia frecuencia (2-5 fps típicamente).
- El filtro de Kalman escala el paso de predicción con el tiempo real entre fotogramas.
- Se trabaja en píxeles (con el tamaño del fotograma de cada detección) para que la relación de
  aspecto del estado sea física.
Los identificadores son temporales y por cámara: no identifican a nadie (sin biometría).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar
from uuid import UUID

import numpy as np
from scipy.optimize import linear_sum_assignment

from security_vision.core.domain.geometry import BBox
from security_vision.core.domain.vision import Detection, Track, TrackState
from security_vision.core.interfaces.analysis import ObjectTracker


@dataclass(frozen=True)
class ByteTrackConfig:
    track_thresh: float = 0.5  # detecciones "altas"
    low_thresh: float = 0.1  # por debajo se descartan
    new_track_thresh: float = 0.6  # confianza mínima para abrir un track nuevo
    match_iou: float = 0.2  # IoU mínimo en la 1.ª asociación (coste 1-IoU <= 0.8, como la referencia)
    low_match_iou: float = 0.5  # IoU mínimo en la 2.ª asociación (detecciones bajas)
    unconfirmed_match_iou: float = 0.3
    min_hits: int = 2  # un track se confirma tras este nº de apariciones
    max_lost_seconds: float = 3.0
    tentative_max_seconds: float = 1.0  # un tentativo sobrevive sin detección como mucho este tiempo
    # Rescate a baja frecuencia: si el IoU es 0 (gran desplazamiento entre análisis), se empareja por
    # distancia entre centros normalizada por la altura predicha, con tamaño compatible.
    rescue_center_dist: float = 1.0  # en alturas de persona
    rescue_size_ratio: float = 1.5
    history: int = 30
    classes: frozenset[str] = frozenset({"person"})


REFERENCE_FPS = 30.0  # ByteTrack se calibró a 30 fps: sus parámetros son "por fotograma de 1/30 s"


class KalmanXYAH:
    """Kalman de velocidad constante sobre (cx, cy, aspecto, alto) — formulación de DeepSORT/ByteTrack.

    La velocidad se expresa por *fotograma de referencia* (1/30 s), como en la referencia, y el paso de
    predicción usa ``dt * 30``. Así los parámetros originales siguen siendo válidos a cualquier fps:
    a 3 fps cada predicción equivale a 10 pasos y la incertidumbre crece en consecuencia.
    """

    _std_pos = 1.0 / 20
    _std_vel = 1.0 / 160

    def __init__(self) -> None:
        self.F = np.eye(8)
        self.H = np.eye(4, 8)

    def initiate(self, z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        mean = np.r_[z, np.zeros(4)]
        h = z[3]
        std = [2 * self._std_pos * h, 2 * self._std_pos * h, 1e-2, 2 * self._std_pos * h,
               10 * self._std_vel * h, 10 * self._std_vel * h, 1e-5, 10 * self._std_vel * h]
        return mean, np.diag(np.square(std))

    def predict(self, mean: np.ndarray, cov: np.ndarray, dt: float) -> tuple[np.ndarray, np.ndarray]:
        steps = max(dt * REFERENCE_FPS, 1e-3)  # nº de fotogramas de referencia transcurridos
        F = self.F.copy()
        F[:4, 4:] = np.eye(4) * steps
        h = mean[3]
        std = [self._std_pos * h, self._std_pos * h, 1e-2, self._std_pos * h,
               self._std_vel * h, self._std_vel * h, 1e-5, self._std_vel * h]
        Q = np.diag(np.square(std)) * steps  # ruido de proceso acumulado en ``steps`` pasos
        return F @ mean, F @ cov @ F.T + Q

    def update(self, mean: np.ndarray, cov: np.ndarray, z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        h = mean[3]
        R = np.diag(np.square([self._std_pos * h, self._std_pos * h, 1e-1, self._std_pos * h]))
        S = self.H @ cov @ self.H.T + R
        K = cov @ self.H.T @ np.linalg.inv(S)
        mean = mean + K @ (z - self.H @ mean)
        cov = (np.eye(8) - K @ self.H) @ cov
        return mean, cov


def _xyah(b: np.ndarray) -> np.ndarray:
    w, h = b[2] - b[0], b[3] - b[1]
    return np.array([b[0] + w / 2, b[1] + h / 2, w / max(h, 1e-6), h])


def _xyxy(m: np.ndarray) -> np.ndarray:
    cx, cy, a, h = m[:4]
    w = a * h
    return np.array([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2])


def iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / np.maximum(area_a[:, None] + area_b[None, :] - inter, 1e-9)


def _assign_distance(tracks: list[_STrack], boxes: np.ndarray, max_dist: float, max_ratio: float
                     ) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Emparejamiento por distancia de centros (en alturas) con compuerta de tamaño."""
    if not tracks or len(boxes) == 0:
        return [], list(range(len(tracks))), list(range(len(boxes)))
    pred = np.stack([t.predicted_xyxy() for t in tracks])
    pc = (pred[:, :2] + pred[:, 2:]) / 2
    ph = pred[:, 3] - pred[:, 1]
    bc = (boxes[:, :2] + boxes[:, 2:]) / 2
    bh = boxes[:, 3] - boxes[:, 1]
    dist = np.linalg.norm(pc[:, None, :] - bc[None, :, :], axis=-1) / np.maximum(ph[:, None], 1e-6)
    ratio = np.maximum(ph[:, None], bh[None, :]) / np.maximum(np.minimum(ph[:, None], bh[None, :]), 1e-6)
    cost = np.where((dist <= max_dist) & (ratio <= max_ratio), dist, 1e6)
    rows, cols = linear_sum_assignment(cost)
    matches = [(r, c) for r, c in zip(rows, cols, strict=True) if cost[r, c] < 1e6]
    mt, md = {r for r, _ in matches}, {c for _, c in matches}
    return matches, [i for i in range(len(tracks)) if i not in mt], [j for j in range(len(boxes)) if j not in md]


def _assign(tracks: list[_STrack], boxes: np.ndarray, min_iou: float,
            scores: np.ndarray | None = None) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    if not tracks or len(boxes) == 0:
        return [], list(range(len(tracks))), list(range(len(boxes)))
    ious = iou_matrix(np.stack([t.predicted_xyxy() for t in tracks]), boxes)
    cost = 1.0 - ious
    if scores is not None:  # fuse_score de ByteTrack: favorece detecciones seguras
        cost = 1.0 - ious * scores[None, :]
    cost = np.where(ious >= min_iou, cost, 1e6)
    rows, cols = linear_sum_assignment(cost)
    matches = [(r, c) for r, c in zip(rows, cols, strict=True) if cost[r, c] < 1e6]
    mt, md = {r for r, _ in matches}, {c for _, c in matches}
    return matches, [i for i in range(len(tracks)) if i not in mt], [j for j in range(len(boxes)) if j not in md]


@dataclass
class _STrack:
    track_id: int
    mean: np.ndarray
    cov: np.ndarray
    det: Detection
    first_seen: datetime
    last_seen: datetime
    hits: int = 1
    state: TrackState = TrackState.TENTATIVE
    history: list[BBox] = field(default_factory=list)
    _pred: np.ndarray | None = None

    def predicted_xyxy(self) -> np.ndarray:
        return _xyxy(self._pred if self._pred is not None else self.mean)


class ByteTracker(ObjectTracker):
    provider_name: ClassVar[str] = "bytetrack"

    def __init__(self, config: ByteTrackConfig | None = None) -> None:
        self.cfg = config or ByteTrackConfig()
        self._kf = KalmanXYAH()
        self.reset()

    def reset(self) -> None:
        self._tracks: list[_STrack] = []
        self._next_id = 1
        self._last_ts: datetime | None = None
        self._camera: UUID | None = None

    # ------------------------------------------------------------------ utilidades
    @staticmethod
    def _px(d: Detection) -> np.ndarray:
        w, h = d.frame_size.width, d.frame_size.height
        return np.array([d.bbox.x1 * w, d.bbox.y1 * h, d.bbox.x2 * w, d.bbox.y2 * h])

    def _to_bbox(self, xyxy: np.ndarray, d: Detection) -> BBox:
        w, h = d.frame_size.width, d.frame_size.height
        x1, y1, x2, y2 = np.clip(xyxy / [w, h, w, h], -0.04, 1.04)
        if x2 - x1 <= 1e-4 or y2 - y1 <= 1e-4:
            return d.bbox
        return BBox(float(x1), float(y1), float(x2), float(y2))

    def _hit(self, t: _STrack, d: Detection, ts: datetime) -> None:
        t.mean, t.cov = self._kf.update(t.mean, t.cov, _xyah(self._px(d)))
        t.det = d
        t.last_seen = ts
        t.hits += 1
        if (t.state is not TrackState.CONFIRMED and t.hits >= self.cfg.min_hits) or t.state is TrackState.LOST:
            t.state = TrackState.CONFIRMED
        t.history.append(self._to_bbox(_xyxy(t.mean), d))
        del t.history[: -self.cfg.history]

    # ------------------------------------------------------------------ API
    def update(self, detections: list[Detection] | tuple[Detection, ...], frame_ts: datetime) -> list[Track]:
        cfg = self.cfg
        dets = [d for d in detections if d.class_name in cfg.classes and d.confidence >= cfg.low_thresh]
        if dets:
            if self._camera is not None and dets[0].camera_id != self._camera:
                raise ValueError("un tracker por cámara: se recibieron detecciones de otra cámara")
            self._camera = dets[0].camera_id
        dt = 0.0 if self._last_ts is None else max(0.0, (frame_ts - self._last_ts).total_seconds())
        self._last_ts = frame_ts
        for t in self._tracks:
            t.mean, t.cov = self._kf.predict(t.mean, t.cov, dt)
            t._pred = t.mean

        high = [d for d in dets if d.confidence >= cfg.track_thresh]
        low = [d for d in dets if d.confidence < cfg.track_thresh]
        hb = np.array([self._px(d) for d in high]).reshape(-1, 4)
        lb = np.array([self._px(d) for d in low]).reshape(-1, 4)
        hs = np.array([d.confidence for d in high])

        active = [t for t in self._tracks if t.state in (TrackState.CONFIRMED, TrackState.LOST)]
        tentative = [t for t in self._tracks if t.state is TrackState.TENTATIVE]

        # 1) confirmados + perdidos  <->  detecciones altas
        m1, un_t, un_h = _assign(active, hb, cfg.match_iou, hs)
        for ti, di in m1:
            self._hit(active[ti], high[di], frame_ts)
        # 1b) rescate por distancia (baja frecuencia de análisis / movimiento rápido)
        if cfg.rescue_center_dist > 0 and un_t and un_h:
            cand_t = [active[i] for i in un_t]
            mr, un_rt, un_rh = _assign_distance(cand_t, hb[un_h], cfg.rescue_center_dist, cfg.rescue_size_ratio)
            for ti, di in mr:
                self._hit(cand_t[ti], high[un_h[di]], frame_ts)
            m1 = m1 + [(un_t[ti], un_h[di]) for ti, di in mr]
            un_t = [un_t[i] for i in un_rt]
            un_h = [un_h[j] for j in un_rh]
        # 2) confirmados aún sin pareja  <->  detecciones bajas (la idea clave de ByteTrack)
        remaining = [active[i] for i in un_t if active[i].state is TrackState.CONFIRMED]
        m2, _, _ = _assign(remaining, lb, cfg.low_match_iou)
        for ti, di in m2:
            self._hit(remaining[ti], low[di], frame_ts)
        matched_ids = {id(remaining[ti]) for ti, _ in m2} | {id(active[ti]) for ti, _ in m1}
        for t in active:
            if id(t) not in matched_ids:
                t.state = TrackState.LOST
        # 3) tentativos  <->  detecciones altas sobrantes
        rest_h = [high[j] for j in un_h]
        rhb = hb[un_h] if len(un_h) else np.zeros((0, 4))
        m3, un_tent, un_h2 = _assign(tentative, rhb, cfg.unconfirmed_match_iou)
        for ti, di in m3:
            self._hit(tentative[ti], rest_h[di], frame_ts)
        if cfg.rescue_center_dist > 0 and un_tent and un_h2:
            cand = [tentative[i] for i in un_tent]
            mr, un_rt, un_rh = _assign_distance(cand, rhb[un_h2], cfg.rescue_center_dist, cfg.rescue_size_ratio)
            for ti, di in mr:
                self._hit(cand[ti], rest_h[un_h2[di]], frame_ts)
            un_tent = [un_tent[i] for i in un_rt]
            un_h2 = [un_h2[j] for j in un_rh]
        # un tentativo sin detección se descarta si supera su tolerancia temporal
        dead = {id(tentative[i]) for i in un_tent
                if (frame_ts - tentative[i].last_seen).total_seconds() > cfg.tentative_max_seconds}
        # 4) tracks nuevos
        for j in un_h2:
            d = rest_h[j]
            if d.confidence < cfg.new_track_thresh:
                continue
            mean, cov = self._kf.initiate(_xyah(self._px(d)))
            t = _STrack(self._next_id, mean, cov, d, frame_ts, frame_ts)
            t.history.append(d.bbox)
            if cfg.min_hits <= 1:
                t.state = TrackState.CONFIRMED
            self._next_id += 1
            self._tracks.append(t)
        # 5) caducidad por tiempo
        self._tracks = [t for t in self._tracks if id(t) not in dead and not (
            t.state is TrackState.LOST and (frame_ts - t.last_seen).total_seconds() > cfg.max_lost_seconds)]
        for t in self._tracks:
            t._pred = None
        return [x for x in self.get_tracks() if x.state is TrackState.CONFIRMED and x.last_seen == frame_ts]

    def get_tracks(self) -> list[Track]:
        out = []
        for t in self._tracks:
            if t.state is TrackState.TENTATIVE:
                continue
            bbox = t.det.bbox if t.last_seen == self._last_ts else self._to_bbox(_xyxy(t.mean), t.det)
            out.append(Track(track_id=t.track_id, camera_id=t.det.camera_id, class_name=t.det.class_name,
                             bbox=bbox, confidence=t.det.confidence, state=t.state, first_seen=t.first_seen,
                             last_seen=t.last_seen, hits=t.hits, history=list(t.history)))
        return out
