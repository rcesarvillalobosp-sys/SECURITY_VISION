"""Motores de inferencia y adaptador DETR con un modelo ONNX diminuto construido en el test.

El grafo imita la interfaz de RT-DETR: entrada ``pixel_values`` [B,3,H,W] -> ``logits`` [B,Q,C] y
``pred_boxes`` [B,Q,4]. Los logits dependen de la media de la imagen para comprobar que la
entrada llega de verdad al modelo.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
import yaml

onnx = pytest.importorskip("onnx")
pytest.importorskip("onnxruntime")
from onnx import TensorProto, helper  # noqa: E402

from security_vision.core.interfaces.inference import DeviceRequest, ModelArtifact, ModelSpec  # noqa: E402
from security_vision.core.interfaces.video import Frame  # noqa: E402
from security_vision.infrastructure.models.store import ModelNotFoundError, ModelStore  # noqa: E402
from security_vision.modules.detection.service import DetectionService  # noqa: E402
from security_vision.plugins.detection_models.detr import RtDetrModel  # noqa: E402
from security_vision.plugins.inference_engines.common import ModelIntegrityError  # noqa: E402
from security_vision.plugins.inference_engines.onnxruntime_engine import OnnxRuntimeEngine  # noqa: E402

Q, C, S = 4, 3, 32  # consultas, clases, tamaño de entrada


def build_tiny_detr(path: Path) -> str:
    # logits[q, c] = base[q, c] + 6 * mean(pixel_values)  (mean en [0,1])
    base = np.full((1, Q, C), -10.0, dtype=np.float32)
    base[0, 0, 0] = 10.0   # consulta 0: clase 0 ("person") muy segura
    base[0, 1, 2] = 0.0    # consulta 1: clase 2 ("dog") 0.5 -> no mapeada, se ignora
    base[0, 2, 1] = -5.0   # consulta 2: clase 1 ("helmet") depende del brillo de la imagen
    boxes = np.array([[[0.5, 0.5, 0.2, 0.4], [0.3, 0.3, 0.1, 0.1], [0.7, 0.2, 0.1, 0.1],
                       [0.1, 0.1, 0.0, 0.0]]], dtype=np.float32)
    nodes = [
        # media POR IMAGEN: [B,3,S,S] -> [B,1,1]
        helper.make_node("ReduceMean", ["pixel_values"], ["m4"], axes=[1, 2, 3], keepdims=1),
        helper.make_node("Squeeze", ["m4", "ax3"], ["m"]),
        helper.make_node("Mul", ["m", "ten"], ["m10"]),
        helper.make_node("Add", ["base", "m10"], ["logits"]),  # [1,Q,C] + [B,1,1] -> [B,Q,C]
        helper.make_node("Shape", ["pixel_values"], ["ishape"]),
        helper.make_node("Slice", ["ishape", "zero", "one"], ["bdim"]),
        helper.make_node("Concat", ["bdim", "q4"], ["bshape"], axis=0),
        helper.make_node("Expand", ["boxes", "bshape"], ["pred_boxes"]),
    ]
    inits = [
        helper.make_tensor("ten", TensorProto.FLOAT, [], [6.0]),
        helper.make_tensor("base", TensorProto.FLOAT, base.shape, base.flatten()),
        helper.make_tensor("boxes", TensorProto.FLOAT, boxes.shape, boxes.flatten()),
        helper.make_tensor("zero", TensorProto.INT64, [1], [0]),
        helper.make_tensor("one", TensorProto.INT64, [1], [1]),
        helper.make_tensor("ax3", TensorProto.INT64, [1], [3]),
        helper.make_tensor("q4", TensorProto.INT64, [2], [Q, 4]),
    ]
    graph = helper.make_graph(
        nodes, "tiny_detr",
        [helper.make_tensor_value_info("pixel_values", TensorProto.FLOAT, ["b", 3, S, S])],
        [helper.make_tensor_value_info("logits", TensorProto.FLOAT, ["b", Q, C]),
         helper.make_tensor_value_info("pred_boxes", TensorProto.FLOAT, ["b", Q, 4])],
        inits)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    onnx.save(model, str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def registry(tmp_path) -> ModelStore:
    d = tmp_path / "tiny" / "1"
    d.mkdir(parents=True)
    digest = build_tiny_detr(d / "model.onnx")
    spec = {"name": "tiny", "version": "1", "architecture": "rtdetr", "artifact": "model.onnx", "sha256": digest,
            "input_size": [S, S], "labels": ["person", "hardhat", "dog"],
            "class_map": {"person": "person", "hardhat": "helmet"}, "score_threshold": 0.4,
            "license": "test", "weights_license": "test", "weights_source": "generado en el test"}
    (d / "model.yaml").write_text(yaml.safe_dump(spec))
    return ModelStore(tmp_path)


def frame(value: int, w: int = 64, h: int = 48) -> Frame:
    return Frame(np.full((h, w, 3), value, dtype=np.uint8), frame_id=7, captured_at=datetime.now(UTC))


def test_store_resolves_and_validates(registry):
    m = registry.get("tiny@1")
    assert m.spec.model_id == "tiny@1" and m.artifact.path.exists()
    with pytest.raises(ModelNotFoundError):
        registry.get("tiny@2")
    with pytest.raises(ModelNotFoundError):
        registry.get("sin-version")


def test_onnxruntime_cpu_engine_and_detr_adapter(registry):
    m = registry.get("tiny@1")
    engine = OnnxRuntimeEngine()
    engine.load_model(m.artifact, DeviceRequest(preference=["cpu"]))
    assert engine.get_device().kind == "cpu"
    model = RtDetrModel(m.spec, engine)
    cam = str(uuid4())
    dark = model.detect([frame(0)], [cam])[0]
    bright = model.detect([frame(255)], [cam])[0]
    # Imagen oscura: solo la persona; la clase "dog" (no mapeada) nunca aparece.
    assert [d.class_name for d in dark] == ["person"]
    # Imagen clara: el logit de casco sube (-5 + 6) -> aparece "helmet" (traducido desde "hardhat").
    assert sorted(d.class_name for d in bright) == ["helmet", "person"]
    p = dark[0]
    assert p.bbox.x1 == pytest.approx(0.4) and p.bbox.y2 == pytest.approx(0.7)
    assert p.frame_size.width == 64 and p.frame_id == 7 and p.model_id == "tiny@1"
    assert str(p.camera_id) == cam and p.confidence > 0.99 and p.inference_ms > 0
    # Batch de 2 imágenes en una llamada
    assert [len(x) for x in model.detect([frame(0), frame(255)], [cam, cam])] == [1, 2]
    assert engine.get_metrics().calls == 3


def test_per_class_threshold(registry):
    m = registry.get("tiny@1")
    engine = OnnxRuntimeEngine()
    engine.load_model(m.artifact, DeviceRequest(preference=["cpu"]))
    strict = m.spec.model_copy(update={"class_thresholds": {"person": 0.99999999}})
    assert RtDetrModel(strict, engine).detect([frame(0)], [str(uuid4())])[0] == []


def test_engine_rejects_tampered_model(registry):
    m = registry.get("tiny@1")
    bad = ModelArtifact(path=m.artifact.path, sha256="0" * 64)
    with pytest.raises(ModelIntegrityError):
        OnnxRuntimeEngine().load_model(bad, DeviceRequest(preference=["cpu"]))


def test_device_fallback_is_explicit(registry):
    m = registry.get("tiny@1")
    engine = OnnxRuntimeEngine()
    engine.load_model(m.artifact, DeviceRequest(preference=["nope", "cpu"]))
    assert engine.get_device().kind == "cpu"
    with pytest.raises(RuntimeError, match="ningún dispositivo"):
        OnnxRuntimeEngine().load_model(m.artifact, DeviceRequest(preference=["nope"]))


def test_switching_engine_does_not_change_results(registry):
    """Criterio 14: cambiar de motor de inferencia no cambia el dominio ni los resultados."""
    pytest.importorskip("openvino")
    from security_vision.plugins.inference_engines.openvino_engine import OpenVinoEngine

    m = registry.get("tiny@1")
    results = []
    for engine, dev in ((OnnxRuntimeEngine(), "cpu"), (OpenVinoEngine(), "openvino-cpu")):
        engine.load_model(m.artifact, DeviceRequest(preference=[dev]))
        dets = RtDetrModel(m.spec, engine).detect([frame(255)], [str(uuid4())])[0]
        results.append([(d.class_name, round(d.confidence, 4), d.bbox) for d in dets])
    assert results[0] == results[1]


def test_detection_service_counts(registry):
    m = registry.get("tiny@1")
    engine = OnnxRuntimeEngine()
    engine.load_model(m.artifact, DeviceRequest(preference=["cpu"]))
    svc = DetectionService(RtDetrModel(m.spec, engine))
    svc.detect(frame(255), str(uuid4()))
    assert svc.stats.calls == 1 and svc.stats.by_class == {"person": 1, "helmet": 1}


def test_spec_rejects_unknown_class_map_labels(registry):
    m = registry.get("tiny@1")
    bad = m.spec.model_copy(update={"class_map": {"casco": "helmet"}})
    with pytest.raises(ValueError, match="casco"):
        RtDetrModel(bad, OnnxRuntimeEngine())


_ = ModelSpec
