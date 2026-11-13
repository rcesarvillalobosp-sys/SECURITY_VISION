"""Visualización de muestras anotadas y hojas de recortes para revisión visual de clases."""

from __future__ import annotations

import random
from collections.abc import Sequence
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from .records import ImageRecord

STATUS_COLORS = {
    "direct": (40, 200, 90),
    "needs_visual_review": (255, 170, 0),
    "excluded": (150, 150, 150),
    None: (230, 40, 40),
}


def _open(rec: ImageRecord) -> Image.Image:
    with Image.open(rec.abs_path) as im:
        return ImageOps.exif_transpose(im).convert("RGB")


def draw_record(rec: ImageRecord, max_side: int = 960) -> Image.Image:
    im = _open(rec)
    scale = min(1.0, max_side / max(im.size))
    if scale < 1.0:
        im = im.resize((round(im.width * scale), round(im.height * scale)))
    d = ImageDraw.Draw(im)
    for b in rec.boxes:
        color = STATUS_COLORS.get(b.mapping_status, STATUS_COLORS[None])
        xy = (b.x1 * im.width, b.y1 * im.height, b.x2 * im.width, b.y2 * im.height)
        d.rectangle(xy, outline=color, width=2)
        label = b.source_class if b.canonical in (None, b.source_class) else f"{b.source_class}→{b.canonical}"
        tx, ty = xy[0], max(0, xy[1] - 12)
        d.rectangle((tx, ty, tx + 7 * len(label) + 4, ty + 12), fill=color)
        d.text((tx + 2, ty), label, fill=(0, 0, 0))
    return im


def save_samples(records: Sequence[ImageRecord], out_dir: Path, per_class: int = 4, seed: int = 0) -> list[Path]:
    """Guarda imágenes anotadas: unas por clase original y todas las que tienen errores (hasta un tope)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    by_class: dict[str, list[ImageRecord]] = {}
    for r in records:
        for c in {b.source_class for b in r.boxes}:
            by_class.setdefault(c, []).append(r)
    chosen: dict[str, ImageRecord] = {}
    for cls, recs in sorted(by_class.items()):
        for r in rng.sample(recs, min(per_class, len(recs))):
            chosen[f"class_{_safe(cls)}__{_safe(r.rel_path)}"] = r
    flagged = [r for r in records if r.issues and r.boxes]
    for r in rng.sample(flagged, min(12, len(flagged))):
        chosen[f"issue_{r.issues[0].code}__{_safe(r.rel_path)}"] = r
    paths = []
    for name, r in chosen.items():
        p = out_dir / f"{name[:150]}.jpg"
        draw_record(r).save(p, quality=88)
        paths.append(p)
    return paths


def crop_sheet(records: Sequence[ImageRecord], source_class: str, out_path: Path, n: int = 64,
               cell: int = 160, seed: int = 0, pad: float = 0.15) -> int:
    """Rejilla de recortes de una clase original: base de la revisión visual (p. ej. boots→safety_boot)."""
    items = [(r, b) for r in records for b in r.boxes if b.source_class == source_class]
    rng = random.Random(seed)
    items = rng.sample(items, min(n, len(items)))
    if not items:
        return 0
    cols = 8
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * cell), (20, 20, 20))
    for k, (r, b) in enumerate(items):
        im = _open(r)
        bw, bh = b.w * im.width, b.h * im.height
        box = (
            max(0, round(b.x1 * im.width - pad * bw)), max(0, round(b.y1 * im.height - pad * bh)),
            min(im.width, round(b.x2 * im.width + pad * bw)), min(im.height, round(b.y2 * im.height + pad * bh)),
        )
        crop = ImageOps.contain(im.crop(box), (cell - 4, cell - 4))
        sheet.paste(crop, ((k % cols) * cell + 2, (k // cols) * cell + 2))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, quality=90)
    return len(items)


def _safe(s: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in s)
