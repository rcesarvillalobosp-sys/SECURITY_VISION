"""Adaptador para detectores de la familia DETR en tiempo real (RT-DETR, RT-DETRv2, RF-DETR, D-FINE...).

Todos comparten la forma de salida: Q consultas con *logits* por clase y cajas cxcywh
normalizadas, sin NMS. Lo que cambia entre ellos (normalización de entrada, nombres de las
entradas/salidas, activación) se declara en ``params`` de ``model.yaml``:

    params:
      input_name: pixel_values      # nombre de la entrada del grafo
      logits_name: logits           # salida [B, Q, C]
      boxes_name: pred_boxes        # salida [B, Q, 4] cxcywh normalizado
      mean: [0, 0, 0]               # normalización tras escalar a [0,1]
      std: [1, 1, 1]
      activation: sigmoid           # sigmoid | softmax (softmax: la última clase es "sin objeto")
      top_k: 300

Preproceso: redimensionado directo (sin *letterbox*) a ``input_size``, como en el entrenamiento
de estos modelos; por eso las cajas normalizadas se aplican tal cual a la imagen original.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any, ClassVar
from uuid import UUID

import numpy as np
from PIL import Image

from security_vision.core.domain.geometry import BBox, Size
from security_vision.core.domain.vision import Detection
from security_vision.core.interfaces.inference import DetectionModel, InferenceEngine, ModelSpec
from security_vision.core.interfaces.video import Frame

DEFAULTS: dict[str, Any] = {"input_name": "pixel_values", "logits_name": "logits", "boxes_name": "pred_boxes",
                            "mean": [0.0, 0.0, 0.0], "std": [1.0, 1.0, 1.0], "activation": "sigmoid",
                            "top_k": 300}


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max(axis=-1, keepdims=True))
    return e / e.sum(axis=-1, keepdims=True)


class DetrDetectionModel(DetectionModel):
    architecture: ClassVar[str] = "detr"

    def __init__(self, spec: ModelSpec, engine: InferenceEngine) -> None:
        super().__init__(spec, engine)
        self.p = {**DEFAULTS, **spec.params}
        self._mean = np.array(self.p["mean"], dtype=np.float32).reshape(1, 3, 1, 1)
        self._std = np.array(self.p["std"], dtype=np.float32).reshape(1, 3, 1, 1)
        unknown = set(spec.class_map) - set(spec.labels)
        if unknown:
            raise ValueError(f"class_map contiene etiquetas que el modelo no tiene: {sorted(unknown)}")
        # índice de salida -> clase canónica (None = clase del modelo que no nos interesa)
        self._canonical: list[str | None] = [spec.class_map.get(lbl) for lbl in spec.labels]
        self._thr = np.array([spec.class_thresholds.get(c, spec.score_threshold) if c else np.inf
                              for c in self._canonical], dtype=np.float32)

    # ------------------------------------------------------------------ pre/post
    def preprocess(self, frames: Sequence[Frame]) -> np.ndarray:
        h, w = self.spec.input_size
        batch = np.empty((len(frames), 3, h, w), dtype=np.float32)
        for i, f in enumerate(frames):
            img = Image.fromarray(f.data).resize((w, h), Image.Resampling.BILINEAR)
            batch[i] = np.asarray(img, dtype=np.float32).transpose(2, 0, 1) / 255.0
        return (batch - self._mean) / self._std

    def postprocess(self, logits: np.ndarray, boxes: np.ndarray) -> list[list[tuple[int, float, np.ndarray]]]:
        """Devuelve, por imagen, (índice de clase, score, caja xyxy normalizada)."""
        softmax = self.p["activation"] == "softmax"
        probs = _softmax(logits)[..., :-1] if softmax else _sigmoid(logits)
        b, q, c = probs.shape
        k = min(int(self.p["top_k"]), q * c)
        out = []
        for i in range(b):
            flat = probs[i].reshape(-1)
            idx = np.argpartition(-flat, k - 1)[:k]
            scores = flat[idx]
            cls = idx % c
            qi = idx // c
            keep = scores >= self._thr[cls]
            res = []
            for s, ci, qq in zip(scores[keep], cls[keep], qi[keep], strict=True):
                cx, cy, bw, bh = boxes[i, qq]
                xyxy = np.clip(np.array([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2]), 0.0, 1.0)
                if xyxy[2] - xyxy[0] <= 1e-4 or xyxy[3] - xyxy[1] <= 1e-4:
                    continue
                res.append((int(ci), float(s), xyxy))
            res.sort(key=lambda t: -t[1])
            out.append(res)
        return out

    # ------------------------------------------------------------------ API
    def detect(self, frames: Sequence[Frame], camera_ids: Sequence[str]) -> list[list[Detection]]:
        if len(frames) != len(camera_ids):
            raise ValueError("frames y camera_ids deben tener la misma longitud")
        if not frames:
            return []
        t0 = time.perf_counter()
        tensor = self.preprocess(frames)
        outputs = self.engine.predict({self.p["input_name"]: tensor})
        elapsed = (time.perf_counter() - t0) * 1000  # preproceso + inferencia
        raw = self.postprocess(outputs[self.p["logits_name"]], outputs[self.p["boxes_name"]])
        model_id = self.spec.model_id
        result: list[list[Detection]] = []
        for f, cam, dets in zip(frames, camera_ids, raw, strict=True):
            size = Size(f.width, f.height)
            cam_uuid = UUID(cam)
            result.append([
                Detection(camera_id=cam_uuid, frame_id=f.frame_id, frame_ts=f.captured_at, frame_size=size,
                          class_name=self._canonical[ci],  # type: ignore[arg-type]
                          bbox=BBox(*map(float, xyxy)), confidence=min(1.0, s), model_id=model_id,
                          inference_ms=elapsed / len(frames))
                for ci, s, xyxy in dets])
        return result

    def warmup(self) -> None:
        h, w = self.spec.input_size
        self.engine.predict({self.p["input_name"]: np.zeros((1, 3, h, w), dtype=np.float32)})


class RtDetrModel(DetrDetectionModel):
    """RT-DETR / RT-DETRv2 exportado desde Hugging Face Transformers (entrada [0,1] sin normalizar)."""

    architecture: ClassVar[str] = "rtdetr"


class RfDetrModel(DetrDetectionModel):
    """RF-DETR (Roboflow, variantes Apache-2.0). Normalización ImageNet; nombres de E/S en model.yaml."""

    architecture: ClassVar[str] = "rfdetr"

    def __init__(self, spec: ModelSpec, engine: InferenceEngine) -> None:
        params = {"mean": [0.485, 0.456, 0.406], "std": [0.229, 0.224, 0.225], "input_name": "input",
                  "logits_name": "labels", "boxes_name": "dets", **spec.params}
        super().__init__(spec.model_copy(update={"params": params}), engine)
