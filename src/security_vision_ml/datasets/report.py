"""Informe de auditoría (Markdown + JSON)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from .quality import DuplicateReport
from .sources import SourceManifest, UsePurpose

PURPOSE_LABEL = {
    UsePurpose.COMMERCIAL_TRAINING: "Entrenamiento (producto)",
    UsePurpose.COMMERCIAL_EVALUATION: "Evaluación (producto)",
    UsePurpose.RESEARCH: "Investigación",
}


def rights_issues(m: SourceManifest, stats: Mapping | None) -> list[str]:
    out = []
    if m.license.status.value != "verified":
        out.append(f"Licencia en estado `{m.license.status.value}`: no utilizable hasta resolverlo.")
    if m.license.commercial_use != "allowed":
        out.append(f"Uso comercial: `{m.license.commercial_use}`.")
    if m.license.share_alike:
        out.append("Cláusula share-alike: obligaciones sobre obras derivadas; no se combina automáticamente.")
    if m.license.attribution_required:
        out.append("Requiere atribución (se incluye en ATTRIBUTION.md de cada exportación).")
    origin = (m.provenance.image_origin or "").lower()
    if not origin:
        out.append("Origen de las imágenes no documentado.")
    if "generad" in origin or "sintét" in origin:
        out.append("Incluye imágenes generadas: la titularidad y el realismo deben considerarse.")
    if stats and stats.get("objects_by_canonical_class", {}).get("person"):
        out.append("Contiene personas identificables potencialmente: tratar como datos personales "
                   "(minimización, acceso restringido, no usar para identificación).")
    return out


def _table(d: Mapping, k1: str, k2: str) -> str:
    if not d:
        return "_(vacío)_\n"
    rows = [f"| {k1} | {k2} |", "|---|---:|"] + [f"| {k} | {v} |" for k, v in d.items()]
    return "\n".join(rows) + "\n"


def write_report(out_dir: Path, manifests: Mapping[str, SourceManifest], stats_by_source: Mapping[str, Mapping],
                 duplicates: DuplicateReport | None, samples: Mapping[str, Sequence[str]],
                 review_sheets: Mapping[str, Mapping[str, str]], orphans: Mapping[str, Sequence[str]],
                 extra_notes: Mapping[str, Sequence[str]] | None = None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    md: list[str] = [f"# Informe de auditoría de datasets EPP\n\nGenerado: {now}. Todas las cifras proceden "
                     "del análisis automático de los archivos descargados; las fuentes no descargadas no "
                     "tienen cifras propias.\n"]

    md.append("## Autorización por uso\n")
    md.append("| Fuente | Licencia | Estado licencia | Comercial | "
              + " | ".join(PURPOSE_LABEL.values()) + " | Descargada |")
    md.append("|---|---|---|---|" + "---|" * len(PURPOSE_LABEL) + "---|")
    for sid, m in manifests.items():
        marks = " | ".join("✅" if m.is_authorized(p) else "❌" for p in PURPOSE_LABEL)
        md.append(f"| {m.name} | {m.license.spdx or m.license.name} | {m.license.status.value} | "
                  f"{m.license.commercial_use} | {marks} | {'sí' if sid in stats_by_source else 'no'} |")
    md.append("")

    for sid, m in manifests.items():
        st = stats_by_source.get(sid)
        md.append(f"## {m.name}\n")
        md.append(f"- **Procedencia:** {m.provenance.publisher} — {m.provenance.homepage}")
        if m.provenance.upstream:
            md.append(f"- **Fuentes aguas arriba:** {', '.join(m.provenance.upstream)}")
        md.append(f"- **Origen de imágenes:** {m.provenance.image_origin or 'no documentado'}")
        md.append(f"- **Licencia:** {m.license.name} ({m.license.url or 's/u'}); evidencia: "
                  f"{m.license.evidence_url}; verificada: {m.license.verified_on or 'no'}")
        if m.license.attribution_text:
            md.append(f"- **Atribución:** {m.license.attribution_text.strip()}")
        if m.license.notes:
            md.append(f"- **Notas de licencia:** {m.license.notes.strip()}")
        md.append("\n### Posibles problemas de derechos\n")
        md += [f"- {x}" for x in rights_issues(m, st)]
        md.append("\n### Mapeo a la taxonomía canónica\n")
        md.append("| Clase original | Destino | Estado efectivo | Motivo |\n|---|---|---|---|")
        for cls in m.class_mapping:
            r = m.effective_mapping(cls)
            md.append(f"| {cls} | {r.target.value if r.target else '—'} | {r.status.value} | {r.reason or ''} |")
        if st:
            md.append("\n### Volumen\n")
            md.append(f"- Imágenes: **{st['images']}** · Objetos: **{st['boxes']}** · "
                      f"Imágenes sin cajas: {st['boxes_per_image']['zero']} · "
                      f"Cajas/imagen: media {st['boxes_per_image']['mean']:.1f}, máx {st['boxes_per_image']['max']}")
            md.append(f"- Particiones originales: {st['splits']}\n")
            md.append("#### Objetos por clase original\n")
            md.append(_table(st["objects_by_original_class"], "Clase", "Objetos"))
            md.append("#### Objetos por clase canónica (todas las cajas mapeadas, incl. pendientes de revisión)\n")
            md.append(_table(st["objects_by_canonical_class"], "Clase", "Objetos"))
            md.append("#### Imágenes que contienen cada clase canónica\n")
            md.append(_table(st["images_by_canonical_class"], "Clase", "Imágenes"))
            md.append("#### Estado de mapeo de las cajas\n")
            md.append(_table(st["mapping_status"], "Estado", "Cajas"))
            md.append("#### Distribución de resolución (lado menor, px)\n")
            md.append(_table(st["resolution_min_side"], "Rango", "Imágenes"))
            md.append("#### Tamaño de objetos (área en px, criterio COCO)\n")
            md.append(_table(st["box_size"], "Tamaño", "Cajas"))
            md.append("#### Calidad de anotaciones (problemas detectados automáticamente)\n")
            md.append(_table(st["issues"], "Problema", "Ocurrencias"))
            md.append(f"Por severidad: {st['issues_by_severity']}\n")
            if orphans.get(sid):
                md.append(f"Etiquetas huérfanas (sin imagen): {len(orphans[sid])}\n")
            if review_sheets.get(sid):
                md.append("#### Hojas de revisión visual pendientes\n")
                md += [f"- `{c}` → `{p}`" for c, p in review_sheets[sid].items()]
                md.append("")
            if samples.get(sid):
                md.append(f"Muestras anotadas: {len(samples[sid])} imágenes en `{Path(samples[sid][0]).parent}`\n")
        md.append("### Limitaciones\n")
        md += [f"- {x}" for x in m.known_limitations]
        for note in (extra_notes or {}).get(sid, []):
            md.append(f"- {note}")
        md.append("")

    if duplicates is not None:
        md.append("## Duplicados\n")
        md.append(f"- Grupos de duplicados exactos (sha256): {len(duplicates.exact_groups)} "
                  f"({sum(len(g) for g in duplicates.exact_groups)} imágenes)")
        md.append(f"- Entre fuentes distintas: {len(duplicates.cross_source_exact)}")
        md.append(f"- Pares casi idénticos (pHash): {len(duplicates.near_pairs)}")
        for a, b, d in duplicates.near_pairs[:15]:
            md.append(f"  - `{a}` ≈ `{b}` (distancia {d})")
        md.append("")

    md.append("## Conclusión operativa\n")
    md.append("El entrenamiento solo puede usar fuentes con ✅ en *Entrenamiento (producto)*, y solo las imágenes "
              "sin cajas pendientes de revisión visual ni errores de anotación. Las clases en "
              "`needs_visual_review` deben revisarse con las hojas de recortes y registrarse en el "
              "manifiesto (`reviews`) antes de exportar.\n")

    md_path = out_dir / "AUDITORIA.md"
    md_path.write_text("\n".join(md), encoding="utf-8")
    (out_dir / "auditoria.json").write_text(json.dumps({
        "generated_at": now,
        "sources": {sid: {"manifest": m.model_dump(mode="json"), "stats": stats_by_source.get(sid)}
                    for sid, m in manifests.items()},
        "duplicates": None if duplicates is None else {
            "exact_groups": duplicates.exact_groups, "near_pairs": duplicates.near_pairs},
    }, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return md_path
