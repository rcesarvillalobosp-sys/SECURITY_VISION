"""CLI ``svds``: gestión de fuentes, auditoría, particiones y exportación.

Ejemplos::

    svds sources
    svds acquire ultralytics_construction_ppe
    svds audit
    svds split --sources ultralytics_construction_ppe --holdout own_site_a
    svds export --name ppe_v1 --sources ultralytics_construction_ppe
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from security_vision.core.domain.taxonomy import CANONICAL_ORDER

from . import acquire as acq
from .corrections import CorrectionSet, export_review_package
from .formats import coco, yolo
from .normalize import build_working_copy, load_index, usable_for_training
from .quality import QualityConfig, check_labels, check_resolution, compute_stats, find_duplicates, record_key
from .records import ImageRecord, Issue, Severity
from .report import write_report
from .sources import CompatibilityError, SourceManifest, UsePurpose, check_combination, load_all
from .split import find_leakage, make_splits
from .visualize import crop_sheet, save_samples

DATA_ROOT = Path("ml/datasets")


def _paths(root: Path) -> dict[str, Path]:
    return {
        "sources": root / "sources",
        "raw": root / "raw",
        "work": root / "work",
        "exports": root / "exports",
        "reports": root / "reports",
        "corrections": root / "corrections",
    }


def _extracted(p: dict[str, Path], m: SourceManifest) -> Path:
    return acq.source_dir(p["raw"], m) / "extracted"


def _work(p: dict[str, Path], m: SourceManifest) -> Path:
    return p["work"] / m.id / m.version


def cmd_sources(args: argparse.Namespace) -> int:
    p = _paths(args.root)
    for m in load_all(p["sources"]).values():
        allowed = ", ".join(sorted(x.value for x in m.allowed_purposes)) or "NINGUNO"
        present = "descargada" if _extracted(p, m).exists() else "no descargada"
        lic = m.license.spdx or m.license.name
        print(f"{m.id:32} {lic:20} {m.license.status.value:20} usos: {allowed} ({present})")
    return 0


def cmd_acquire(args: argparse.Namespace) -> int:
    p = _paths(args.root)
    m = load_all(p["sources"])[args.source]
    try:
        archive = acq.download(m, p["raw"], UsePurpose(args.purpose))
    except acq.AcquisitionError as exc:
        print(f"RECHAZADO: {exc}", file=sys.stderr)
        return 2
    acq.extract(archive, _extracted(p, m))
    print(f"OK: {archive}")
    return 0


def _read_source(m: SourceManifest, root: Path) -> list[ImageRecord]:
    fmt = m.download.format if m.download else m.local_format
    if fmt == "yolo":
        return list(yolo.read_dataset(root, m.id))
    ann = next(p for p in root.rglob("*.json") if p.name != ".extracted.json")
    return list(coco.read_dataset(ann, ann.parent.parent / "images", m.id))


def _verify_bundled_hashes(records: Sequence[ImageRecord], root: Path) -> list[str]:
    """Si el dataset trae un manifest.jsonl con sha256 por archivo, se contrasta."""
    notes = []
    for mf in root.rglob("manifest.jsonl"):
        expected = {}
        for line in mf.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if "file" in row and "sha256" in row:
                expected[row["file"]] = row["sha256"]
        by_name = {Path(r.rel_path).name: r for r in records}
        mismatch = [f for f, h in expected.items() if f in by_name and by_name[f].sha256 != h]
        missing = [f for f in expected if f not in by_name]
        notes.append(f"Integridad contra `{mf.name}` del publicador: {len(expected)} entradas, "
                     f"{len(mismatch)} sha256 distintos, {len(missing)} archivos ausentes.")
        for r in records:
            if Path(r.rel_path).name in mismatch:
                r.issues.append(Issue("sha256_mismatch", Severity.ERROR, "difiere del manifiesto del publicador"))
    return notes


def cmd_audit(args: argparse.Namespace) -> int:
    p = _paths(args.root)
    manifests = load_all(p["sources"])
    cfg = QualityConfig(min_image_side=args.min_side)
    all_records: list[ImageRecord] = []
    stats, samples, sheets, orphans, notes = {}, {}, {}, {}, {}
    reports_dir = p["reports"]
    for sid, m in manifests.items():
        root = _extracted(p, m)
        if not root.exists():
            continue
        print(f"[{sid}] leyendo y normalizando…")
        records = _read_source(m, root)
        corr = CorrectionSet.load(p["corrections"], m)
        records = build_working_copy(records, m, _work(p, m), corr)
        notes[sid] = _verify_bundled_hashes(records, root)
        for a in corr.applied:
            n = sum(a.meta.id in r.corrections for r in records)
            notes[sid].append(f"Corrección `{a.meta.id}` ({a.meta.scope_class}) aplicada a {n} imágenes; "
                              f"revisor: {a.meta.reviewer}, {a.meta.completed_on}.")
        for meta in corr.pending:
            notes[sid].append(f"Corrección `{meta.id}` ({meta.scope_class}) PENDIENTE de re-etiquetado en CVAT.")
        notes[sid] += [f"Problema en correcciones: {x}" for x in corr.problems]
        annotates_person = any(r.target and r.target.value == "person" for r in m.class_mapping.values())
        for r in records:
            check_resolution(r, cfg)
            check_labels(r, cfg, annotates_person)
        orphans[sid] = yolo.find_orphan_labels(root)
        # Re-escribe el índice con los problemas de calidad incluidos.
        with (_work(p, m) / "index.jsonl").open("w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r.to_json(), ensure_ascii=False) + "\n")
        stats[sid] = compute_stats(records)
        usable = sum(usable_for_training(r) for r in records)
        notes[sid].append(f"Imágenes utilizables para entrenamiento hoy (sin errores ni cajas pendientes de "
                          f"revisión): {usable} de {len(records)}.")
        if not args.no_samples:
            samples[sid] = [str(x) for x in save_samples(records, reports_dir / "samples" / sid)]
            sheets[sid] = {}
            for cls in m.class_mapping:
                if m.effective_mapping(cls).status.value == "needs_visual_review":
                    out = reports_dir / "review" / sid / f"{cls}.jpg"
                    if crop_sheet(records, cls, out, n=args.sheet_size):
                        sheets[sid][cls] = out.as_posix()
        all_records += records
    dups = find_duplicates(all_records, cfg)
    path = write_report(reports_dir, manifests, stats, dups, samples, sheets, orphans, notes)
    print(f"Informe: {path}")
    return 0


def cmd_review_export(args: argparse.Namespace) -> int:
    p = _paths(args.root)
    m = load_all(p["sources"])[args.source]
    records = list(load_index(_work(p, m)))
    out = p["exports"] / "review" / args.correction_id
    try:
        pkg = export_review_package(records, m, args.source_class, args.correction_id, out, p["corrections"])
    except (ValueError, FileExistsError) as exc:
        print(f"RECHAZADO: {exc}", file=sys.stderr)
        return 2
    print(f"Paquete CVAT: {out} ({len(pkg['images'])} imágenes, {pkg['boxes_in_scope']} cajas "
          f"'{args.source_class}'). Instrucciones: {out / 'INSTRUCCIONES.md'}")
    return 0


def _load_records(p: dict[str, Path], manifests: dict[str, SourceManifest], ids: Sequence[str]) -> list[ImageRecord]:
    out = []
    for sid in ids:
        out += list(load_index(_work(p, manifests[sid])))
    return out


def cmd_split(args: argparse.Namespace) -> int:
    p = _paths(args.root)
    manifests = load_all(p["sources"])
    ids = list(dict.fromkeys(args.sources + args.holdout))
    try:
        check_combination([manifests[s] for s in args.sources], UsePurpose.COMMERCIAL_TRAINING)
        check_combination([manifests[s] for s in args.holdout], UsePurpose.COMMERCIAL_EVALUATION)
    except CompatibilityError as exc:
        print(f"RECHAZADO: {exc}", file=sys.stderr)
        return 2
    records = [r for r in _load_records(p, manifests, ids) if usable_for_training(r)]
    res = make_splits(records, tuple(args.ratios), set(args.holdout), args.seed, sequence_pattern=args.sequence_pattern)
    leaks = find_leakage(records, res.assignment)
    out = p["work"] / "splits" / f"{args.name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"sources": args.sources, "holdout": args.holdout, "seed": args.seed,
                               "ratios": args.ratios, "images": res.image_counts, "classes": res.class_counts,
                               "leaks": leaks, "assignment": res.assignment}, indent=1), encoding="utf-8")
    print(json.dumps({"images": res.image_counts, "classes": res.class_counts, "leaks": len(leaks)}, indent=1))
    print(f"Partición: {out}")
    return 1 if leaks else 0


def cmd_export(args: argparse.Namespace) -> int:
    p = _paths(args.root)
    manifests = load_all(p["sources"])
    split = json.loads((p["work"] / "splits" / f"{args.split}.json").read_text(encoding="utf-8"))
    if split["leaks"]:
        print("RECHAZADO: la partición tiene fugas", file=sys.stderr)
        return 2
    ids = list(dict.fromkeys(split["sources"] + split["holdout"]))
    records = {record_key(r): r for r in _load_records(p, manifests, ids)}
    dest = p["exports"] / args.split
    if dest.exists():
        print(f"RECHAZADO: {dest} ya existe", file=sys.stderr)
        return 2
    for key, s in split["assignment"].items():
        r = records[key]
        stem = f"{r.source_id}__{Path(r.rel_path).stem}"
        img_out = dest / "images" / s / f"{stem}{Path(r.abs_path).suffix}"
        img_out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(r.abs_path, img_out)
        src_lbl = _work(p, manifests[r.source_id]) / "labels" / Path(r.rel_path).with_suffix(".txt")
        lbl_out = dest / "labels" / s / f"{stem}.txt"
        lbl_out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src_lbl, lbl_out)
    names = "\n".join(f"  {i}: {c.value}" for i, c in enumerate(CANONICAL_ORDER))
    (dest / "data.yaml").write_text(
        f"path: .\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n{names}\n", encoding="utf-8")
    attribution = ["# Atribuciones y licencias de los datos\n"]
    for sid in ids:
        m = manifests[sid]
        attribution.append(f"## {m.name}\n- Licencia: {m.license.name} ({m.license.url})\n"
                           f"- Atribución: {(m.license.attribution_text or '').strip()}\n"
                           "- Cambios: anotaciones convertidas a la taxonomía canónica de Security Vision; "
                           "clases fuera de la taxonomía eliminadas; imágenes sin modificar.\n")
    (dest / "ATTRIBUTION.md").write_text("\n".join(attribution), encoding="utf-8")
    print(f"Exportado: {dest}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="svds", description="Gestión y auditoría de datasets EPP")
    ap.add_argument("--root", type=Path, default=DATA_ROOT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sources").set_defaults(func=cmd_sources)
    a = sub.add_parser("acquire")
    a.add_argument("source")
    a.add_argument("--purpose", default=UsePurpose.COMMERCIAL_TRAINING.value, choices=[u.value for u in UsePurpose])
    a.set_defaults(func=cmd_acquire)
    au = sub.add_parser("audit")
    au.add_argument("--min-side", type=int, default=320)
    au.add_argument("--sheet-size", type=int, default=64)
    au.add_argument("--no-samples", action="store_true")
    au.set_defaults(func=cmd_audit)
    s = sub.add_parser("split")
    s.add_argument("--name", required=True)
    s.add_argument("--sources", nargs="+", required=True)
    s.add_argument("--holdout", nargs="*", default=[])
    s.add_argument("--ratios", nargs=3, type=float, default=[0.8, 0.1, 0.1])
    s.add_argument("--seed", type=int, default=42)
    s.add_argument("--sequence-pattern", default=None,
                   help="regex con grupo 'seq' para agrupar fotogramas de un mismo vídeo, p. ej. '(?P<seq>.+)_f\\d+'")
    s.set_defaults(func=cmd_split)
    rv = sub.add_parser("review-export", help="paquete CVAT para re-etiquetar una clase dudosa")
    rv.add_argument("source")
    rv.add_argument("--source-class", required=True)
    rv.add_argument("--correction-id", required=True)
    rv.set_defaults(func=cmd_review_export)
    e = sub.add_parser("export")
    e.add_argument("--split", required=True)
    e.set_defaults(func=cmd_export)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
