from __future__ import annotations

import zipfile
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from pydantic import ValidationError

from security_vision_ml.datasets import acquire as acq
from security_vision_ml.datasets.formats import yolo
from security_vision_ml.datasets.imaging import inspect_image, phash
from security_vision_ml.datasets.normalize import build_working_copy, canonical_yolo_lines, usable_for_training
from security_vision_ml.datasets.quality import QualityConfig, check_labels, check_resolution, find_duplicates
from security_vision_ml.datasets.records import Box, ImageRecord
from security_vision_ml.datasets.sources import (
    CompatibilityError,
    MappingReview,
    SourceManifest,
    UsePurpose,
    check_combination,
    load_all,
)
from security_vision_ml.datasets.split import find_leakage, make_splits

REPO = Path(__file__).resolve().parents[3]


def manifest(**over) -> SourceManifest:
    base = {
        "id": "src_a",
        "name": "A",
        "version": "1",
        "license": {
            "name": "CC BY 4.0", "spdx": "CC-BY-4.0", "evidence_url": "https://x", "status": "verified",
            "commercial_use": "allowed", "verified_on": "2026-11-12",
        },
        "provenance": {"publisher": "p", "homepage": "https://x", "image_origin": "own"},
        "allowed_purposes": ["commercial_training", "commercial_evaluation"],
        "class_mapping": {
            "Person": {"target": "person", "status": "direct"},
            "helmet": {"target": "helmet", "status": "direct"},
            "no_helmet": {"target": "no_helmet", "status": "direct"},
            "boots": {"target": "safety_boot", "status": "needs_visual_review"},
            "forklift": {"status": "excluded"},
        },
    }
    base.update(over)
    return SourceManifest.model_validate(base)


def make_image(path: Path, size=(640, 480), seed=0, pattern=None) -> None:
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8) if pattern is None else pattern
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr).save(path)


# --- licencias y políticas -------------------------------------------------

def test_project_manifests_load_and_only_ultralytics_is_authorized():
    ms = load_all(REPO / "ml/datasets/sources")
    assert set(ms) == {
        "ultralytics_construction_ppe", "cognisightlabs_ppe_detection", "roboflow_ppe_sheperd_v0", "sh17",
    }
    authorized = {k for k, m in ms.items() if m.is_authorized(UsePurpose.COMMERCIAL_TRAINING)}
    assert authorized == {"ultralytics_construction_ppe"}
    # SH17: shoes nunca se trata como safety_boot
    assert ms["sh17"].effective_mapping("Shoes").target is None


def test_non_commercial_license_cannot_authorize_commercial_use():
    with pytest.raises(ValidationError):
        manifest(license={"name": "CC BY-NC", "evidence_url": "https://x", "status": "verified",
                          "commercial_use": "forbidden"})


def test_unverified_license_cannot_authorize_anything():
    with pytest.raises(ValidationError):
        manifest(license={"name": "?", "evidence_url": "https://x", "status": "unverified",
                          "commercial_use": "unknown"}, allowed_purposes=["research"])


def test_visual_review_changes_effective_mapping():
    m = manifest()
    assert m.effective_mapping("boots").status.value == "needs_visual_review"
    ok = manifest(reviews=[MappingReview(source_class="boots", decision="approved", reviewer="r",
                                         reviewed_on=date(2026, 11, 12), sample_size=64)])
    assert ok.effective_mapping("boots").status.value == "direct"
    ko = manifest(reviews=[MappingReview(source_class="boots", decision="rejected", reviewer="r",
                                         reviewed_on=date(2026, 11, 12), sample_size=64)])
    assert ko.effective_mapping("boots").target is None
    assert m.effective_mapping("unknown_cls").status.value == "excluded"


def test_incompatible_sources_are_not_combined():
    a = manifest()
    nc = manifest(id="nc", license={"name": "NC", "evidence_url": "https://x", "status": "verified",
                                    "commercial_use": "forbidden", "share_alike": True}, allowed_purposes=["research"])
    with pytest.raises(CompatibilityError):
        check_combination([a, nc], UsePurpose.COMMERCIAL_TRAINING)
    check_combination([a], UsePurpose.COMMERCIAL_TRAINING)


def test_download_refused_when_not_authorized(tmp_path):
    m = manifest(allowed_purposes=["commercial_evaluation"],
                 download={"url": "https://example.invalid/x.zip", "filename": "x.zip", "format": "yolo"})
    with pytest.raises(acq.AcquisitionError):
        acq.download(m, tmp_path, UsePurpose.COMMERCIAL_TRAINING)
    assert not any(tmp_path.iterdir())


def test_extract_blocks_zip_slip(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.txt", "x")
    with pytest.raises(acq.AcquisitionError):
        acq.extract(archive, tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()


def test_extract_is_read_only(tmp_path):
    archive = tmp_path / "ok.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("d/a.txt", "x")
    out = acq.extract(archive, tmp_path / "out")
    with pytest.raises(PermissionError):
        (out / "d/a.txt").write_text("y")


# --- lectura y normalización --------------------------------------------------

def build_yolo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "data.yaml").write_text("names:\n  0: helmet\n  1: boots\n  2: Person\n  3: forklift\n  4: no_helmet\n")
    make_image(root / "images/train/a.jpg", seed=1)
    (root / "labels/train").mkdir(parents=True)
    (root / "labels/train/a.txt").write_text("2 0.5 0.5 0.4 0.8\n0 0.5 0.2 0.1 0.1\n3 0.1 0.1 0.1 0.1\n")
    make_image(root / "images/train/b.jpg", seed=2)
    (root / "labels/train/b.txt").write_text("1 0.5 0.9 0.1 0.05\n9 0.5 0.5 0.1 0.1\nbad line\n0 0.5 0.5 0 0.1\n")
    make_image(root / "images/val/c.jpg", seed=3)  # sin etiqueta
    (root / "labels/val").mkdir(parents=True)
    (root / "labels/val/orphan.txt").write_text("")


def test_yolo_reader_reports_label_problems(tmp_path):
    build_yolo(tmp_path)
    recs = {r.rel_path: r for r in yolo.read_dataset(tmp_path, "src_a")}
    assert recs["images/train/a.jpg"].original_split == "train"
    codes_b = {i.code for i in recs["images/train/b.jpg"].issues}
    assert {"unknown_class_id", "malformed_line", "degenerate_box"} <= codes_b
    assert not recs["images/val/c.jpg"].has_label_file
    assert yolo.find_orphan_labels(tmp_path) == ["labels/val/orphan.txt"]


def test_normalization_keeps_originals_and_blocks_pending_review(tmp_path):
    src = tmp_path / "raw"
    build_yolo(src)
    before = (src / "labels/train/a.txt").read_text()
    recs = {r.rel_path: r for r in build_working_copy(yolo.read_dataset(src, "src_a"), manifest(), tmp_path / "work")}
    assert (src / "labels/train/a.txt").read_text() == before
    a = recs["images/train/a.jpg"]
    assert usable_for_training(a)
    lines = canonical_yolo_lines(a)
    assert len(lines) == 2  # forklift excluido
    assert lines[0].startswith("0 ")  # person -> índice 0
    assert not usable_for_training(recs["images/train/b.jpg"])  # boots pendiente + errores
    assert (tmp_path / "work/index.jsonl").exists()
    assert a.width == 640 and a.sha256 and a.phash is not None


# --- calidad -----------------------------------------------------------------

def test_quality_checks():
    cfg = QualityConfig()
    r = ImageRecord("s", "x.jpg", "x.jpg", "train", width=200, height=150)
    r.boxes = [
        Box("Person", 0.1, 0.1, 0.4, 0.9, canonical="person", mapping_status="direct"),
        Box("helmet", 0.2, 0.1, 0.3, 0.2, canonical="helmet", mapping_status="direct"),
        Box("no_helmet", 0.2, 0.1, 0.3, 0.2, canonical="no_helmet", mapping_status="direct"),
        Box("helmet", 0.8, 0.8, 0.82, 0.82, canonical="helmet", mapping_status="direct"),
    ]
    check_resolution(r, cfg)
    check_labels(r, cfg, source_annotates_person=True)
    codes = [i.code for i in r.issues]
    assert "low_resolution" in codes
    assert "contradictory_labels" in codes
    assert "ppe_without_person" in codes
    assert "tiny_box" in codes


def test_phash_robust_to_resize_and_detects_duplicates(tmp_path):
    rng = np.random.default_rng(7)
    base = (rng.integers(0, 255, (60, 80, 3))).repeat(8, 0).repeat(8, 1).astype(np.uint8)
    make_image(tmp_path / "a.png", pattern=base)
    Image.fromarray(base).resize((320, 240)).save(tmp_path / "b.png")
    make_image(tmp_path / "c.png", seed=99)
    (tmp_path / "d.png").write_bytes((tmp_path / "a.png").read_bytes())
    recs = [ImageRecord("s", n, str(tmp_path / n), None) for n in ("a.png", "b.png", "c.png", "d.png")]
    for r in recs:
        inspect_image(r)
    with Image.open(tmp_path / "a.png") as a, Image.open(tmp_path / "b.png") as b:
        assert bin(phash(a) ^ phash(b)).count("1") <= 6
    dups = find_duplicates(recs, QualityConfig())
    assert dups.exact_groups == [["s::a.png", "s::d.png"]]
    near = {(x, y) for x, y, _ in dups.near_pairs}
    assert ("s::a.png", "s::b.png") in near or ("s::b.png", "s::d.png") in near
    assert not any("c.png" in x or "c.png" in y for x, y in near)


# --- particiones -----------------------------------------------------------------

def test_split_has_no_leakage_and_holdout_goes_to_test(tmp_path):
    recs = []
    for i in range(40):
        rng = np.random.default_rng(i)
        base = (rng.integers(0, 255, (30, 40, 3))).repeat(16, 0).repeat(16, 1).astype(np.uint8)
        # 3 "fotogramas" casi idénticos por vídeo
        for f in range(3):
            frame = base.copy()
            frame[0:4, 0:4] = f * 40
            p = tmp_path / f"vid{i}_f{f}.png"
            Image.fromarray(frame).save(p)
            r = ImageRecord("pub" if i < 35 else "own", p.name, str(p), None)
            inspect_image(r)
            r.boxes = [Box("helmet", 0.1, 0.1, 0.3, 0.3, canonical="helmet", mapping_status="direct")]
            recs.append(r)
    res = make_splits(recs, holdout_sources={"own"}, seed=1)
    assert find_leakage(recs, res.assignment) == []
    assert all(res.assignment[f"own::{r.rel_path}"] == "test" for r in recs if r.source_id == "own")
    assert res.image_counts["train"] > res.image_counts.get("val", 0)
    # cada vídeo entero en una sola partición
    for i in range(35):
        assert len({res.assignment[f"pub::vid{i}_f{f}.png"] for f in range(3)}) == 1


def test_every_canonical_class_has_definition():
    from security_vision.core.domain.taxonomy import CLASS_DEFINITIONS, CanonicalClass

    assert set(CLASS_DEFINITIONS) == set(CanonicalClass)
    assert "NO certifica" in CLASS_DEFINITIONS[CanonicalClass.SAFETY_BOOT]


def test_project_boots_review_is_applied():
    m = load_all(REPO / "ml/datasets/sources")["ultralytics_construction_ppe"]
    assert m.effective_mapping("boots").status.value == "direct"
    assert m.effective_mapping("no_boots").status.value == "needs_visual_review"


# --- correcciones (re-etiquetado en CVAT) ---------------------------------------

def _gated_manifest() -> SourceManifest:
    return manifest(
        class_mapping={
            "Person": {"target": "person", "status": "direct"},
            "boots": {"target": "safety_boot", "status": "direct"},
            "no_boots": {"target": "no_safety_boot", "status": "needs_visual_review"},
        },
        reviews=[MappingReview(source_class="no_boots", decision="approved", reviewer="r",
                               reviewed_on=date(2026, 11, 12), sample_size=64, requires_correction="fix1")],
    )


def _corr_dataset(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "data.yaml").write_text("names:\n  0: Person\n  1: boots\n  2: no_boots\n")
    for name, seed, lines in (("a", 1, "0 0.5 0.5 0.4 0.8\n2 0.5 0.9 0.1 0.05\n"),
                              ("b", 2, "0 0.5 0.5 0.4 0.8\n2 0.4 0.9 0.1 0.05\n"),
                              ("c", 3, "0 0.5 0.5 0.4 0.8\n1 0.5 0.9 0.1 0.05\n")):
        make_image(root / f"images/train/{name}.jpg", seed=seed)
        (root / "labels/train").mkdir(parents=True, exist_ok=True)
        (root / f"labels/train/{name}.txt").write_text(lines)


def test_review_package_and_correction_overlay(tmp_path):
    import json

    import yaml

    from security_vision_ml.datasets.corrections import CorrectionSet, export_review_package

    m = _gated_manifest()
    raw, corr_root = tmp_path / "raw", tmp_path / "corrections"
    _corr_dataset(raw)
    recs = build_working_copy(yolo.read_dataset(raw, m.id), m, tmp_path / "w0")
    # Sin corrección: no_boots bloquea a y b; c es utilizable.
    assert [usable_for_training(r) for r in recs] == [False, False, True]

    pkg = export_review_package(recs, m, "no_boots", "fix1", tmp_path / "pkg", corr_root)
    assert sorted(pkg["images"]) == ["images__train__a.jpg", "images__train__b.jpg"]
    assert pkg["boxes_in_scope"] == 2
    with zipfile.ZipFile(tmp_path / "pkg/anotaciones_coco.zip") as zf:
        coco_json = json.loads(zf.read("annotations/instances_default.json"))
    assert len(coco_json["annotations"]) == 4  # contexto completo: personas incluidas

    # Pendiente: no cambia nada.
    pending = CorrectionSet.load(corr_root, m)
    assert [x.id for x in pending.pending] == ["fix1"] and not pending.applied

    # Simula la exportación de CVAT: en 'a' el revisor cambia no_boots -> boots.
    cats = {c["name"]: c["id"] for c in coco_json["categories"]}
    for ann in coco_json["annotations"]:
        if ann["image_id"] == 1 and ann["category_id"] == cats["no_boots"]:
            ann["category_id"] = cats["boots"]
    reg = corr_root / m.id / "fix1"
    (reg / "instances_default.json").write_text(json.dumps(coco_json))
    meta = yaml.safe_load((reg / "correction.yaml").read_text())
    meta.update(status="completed", reviewer="tester", completed_on="2026-11-13")
    (reg / "correction.yaml").write_text(yaml.safe_dump(meta))

    before = (raw / "labels/train/a.txt").read_text()
    corr = CorrectionSet.load(corr_root, m)
    recs = {r.rel_path: r for r in build_working_copy(yolo.read_dataset(raw, m.id), m, tmp_path / "w1", corr)}
    a, b = recs["images/train/a.jpg"], recs["images/train/b.jpg"]
    assert (raw / "labels/train/a.txt").read_text() == before  # original intacto
    assert a.corrections == ["fix1"] and {x.source_class for x in a.boxes} == {"Person", "boots"}
    assert all(usable_for_training(r) for r in recs.values())
    assert any(x.canonical == "no_safety_boot" and x.mapping_status == "direct" for x in b.boxes)


def test_correction_rejected_if_image_changed(tmp_path):
    from security_vision_ml.datasets.corrections import CorrectionMeta, CorrectionSet, _Applied

    rec = ImageRecord("s", "x.jpg", "x.jpg", None, sha256="nuevo")
    rec.boxes = [Box("no_boots", 0, 0, 1, 1)]
    meta = CorrectionMeta(id="fix1", source_id="s", source_version="1", scope_class="no_boots", status="completed")
    cs = CorrectionSet(applied=[_Applied(meta, {"x.jpg": ("viejo", [Box("boots", 0, 0, 1, 1)])})])
    cs.apply(rec)
    assert rec.corrections == [] and rec.boxes[0].source_class == "no_boots"
    assert any(i.code == "correction_image_mismatch" for i in rec.issues)
