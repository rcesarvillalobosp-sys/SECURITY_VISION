"""Escenarios sintéticos de seguimiento con verdad conocida (no sustituyen a vídeo real anotado).

Personas que caminan en un plano 1280x720 analizado a ``fps`` con ruido de detector realista:
jitter de cajas, confianza variable, detecciones perdidas (falsos negativos), falsos positivos
esporádicos y oclusiones (dos personas que se cruzan, detecciones de baja confianza al solaparse).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import numpy as np

from security_vision.core.domain.geometry import BBox, Size
from security_vision.core.domain.vision import Detection

W, H = 1280, 720
CAM = UUID("01890000-0000-7000-8000-0000000000aa")


@dataclass
class Scenario:
    name: str
    fps: float
    gt: list[list[tuple[int, list[float]]]]  # por fotograma: (id, xyxy en px)
    dets: list[list[Detection]]
    timestamps: list[datetime]


def _person_box(cx: float, feet_y: float, height: float) -> list[float]:
    w = height * 0.38
    return [cx - w / 2, feet_y - height, cx + w / 2, feet_y]


def make_scenario(name: str, *, seed: int = 0, fps: float = 3.0, seconds: float = 20.0, people: int = 4,
                  speed_px_s: float = 80.0, miss_rate: float = 0.1, fp_rate: float = 0.05, jitter: float = 0.04,
                  crossing: bool = False) -> Scenario:
    rng = np.random.default_rng(seed)
    n = int(seconds * fps)
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    ppl = []
    for i in range(people):
        height = rng.uniform(180, 320)
        if crossing and i < 2:  # dos personas que se cruzan de frente a la misma altura
            x0, vx = (200.0, speed_px_s) if i == 0 else (W - 200.0, -speed_px_s)
            y0, vy = 520.0, 0.0
        else:
            x0, y0 = rng.uniform(150, W - 150), rng.uniform(300, H - 20)
            ang = rng.uniform(0, 2 * np.pi)
            vx, vy = speed_px_s * np.cos(ang), 0.4 * speed_px_s * np.sin(ang)
        ppl.append([i + 1, x0, y0, vx, vy, height])
    gt, dets, ts = [], [], []
    for k in range(n):
        t = k / fps
        frame_gt, frame_dets = [], []
        boxes = []
        for pid, x0, y0, vx, vy, h in ppl:
            x = x0 + vx * t
            y = y0 + vy * t
            # rebote en los bordes
            x = abs((x - 100) % (2 * (W - 200)) - (W - 200)) + 100
            y = abs((y - 250) % (2 * (H - 270)) - (H - 270)) + 250
            hh = h * (0.7 + 0.3 * (y / H))  # perspectiva: más lejos = más pequeño
            box = _person_box(x, y, hh)
            boxes.append((pid, box))
            frame_gt.append((pid, box))
        for pid, box in boxes:
            # oclusión: si otra persona está delante (más abajo en la imagen) y solapa mucho
            occluded = any(o_pid != pid and o_box[3] > box[3] and _overlap(box, o_box) > 0.5
                           for o_pid, o_box in boxes)
            if rng.random() < (0.6 if occluded else miss_rate):
                continue
            hgt = box[3] - box[1]
            noisy = np.array(box) + rng.normal(0, jitter * hgt, 4)
            conf = float(np.clip(rng.normal(0.35 if occluded else 0.8, 0.1), 0.11, 0.99))
            frame_dets.append(_det(noisy, conf, k, t0 + timedelta(seconds=t)))
        if rng.random() < fp_rate:
            fx, fy = rng.uniform(100, W - 100), rng.uniform(300, H)
            frame_dets.append(_det(np.array(_person_box(fx, fy, 150)), float(rng.uniform(0.5, 0.7)), k,
                                   t0 + timedelta(seconds=t)))
        gt.append(frame_gt)
        dets.append(frame_dets)
        ts.append(t0 + timedelta(seconds=t))
    return Scenario(name, fps, gt, dets, ts)


def _overlap(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    area = (a[2] - a[0]) * (a[3] - a[1])
    return ix * iy / area if area > 0 else 0.0


def _det(box: np.ndarray, conf: float, k: int, ts: datetime) -> Detection:
    x1, y1, x2, y2 = np.clip(box, [0, 0, 0, 0], [W, H, W, H]) / [W, H, W, H]
    x2, y2 = max(x2, x1 + 1e-3), max(y2, y1 + 1e-3)
    return Detection(camera_id=CAM, frame_id=k, frame_ts=ts, frame_size=Size(W, H), class_name="person",
                     bbox=BBox(float(x1), float(y1), float(x2), float(y2)), confidence=conf, model_id="sintetico@1",
                     inference_ms=0.0)


STANDARD_SCENARIOS = {
    "tranquilo_3fps": dict(fps=3, people=3, speed_px_s=60, miss_rate=0.05, fp_rate=0.02),
    "concurrido_3fps": dict(fps=3, people=8, speed_px_s=80, miss_rate=0.1, fp_rate=0.05),
    "cruce_3fps": dict(fps=3, people=2, speed_px_s=120, miss_rate=0.05, fp_rate=0.0, crossing=True),
    "rapido_2fps": dict(fps=2, people=4, speed_px_s=160, miss_rate=0.1, fp_rate=0.05),
    "detector_malo_3fps": dict(fps=3, people=5, speed_px_s=80, miss_rate=0.3, fp_rate=0.15, jitter=0.08),
}
