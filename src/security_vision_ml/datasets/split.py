"""Particiones train/val/test sin fuga entre particiones.

1. Se agrupan imágenes relacionadas: duplicados exactos, casi-duplicados (pHash),
   copias aumentadas de Roboflow (``*_jpg.rf.<hash>``) y secuencias de vídeo
   (patrón configurable sobre el nombre de archivo).
2. Cada GRUPO completo va a una sola partición, intentando respetar las proporciones
   por clase (asignación voraz por déficit).
3. Las fuentes de "holdout" (p. ej. fotos y vídeos propios reales) van íntegras a
   ``test`` y nunca participan en el entrenamiento.
"""

from __future__ import annotations

import random
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from .imaging import hamming_matrix_row
from .quality import record_key
from .records import ImageRecord

SPLITS = ("train", "val", "test")
ROBOFLOW_AUG = re.compile(r"_(jpe?g|png)\.rf\.[0-9a-f]+$", re.IGNORECASE)


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def base_name(rel_path: str, sequence_pattern: re.Pattern[str] | None) -> str:
    stem = rel_path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    stem = ROBOFLOW_AUG.sub("", stem)
    if sequence_pattern is not None and (m := sequence_pattern.match(stem)):
        return m.group("seq")
    return stem


def assign_groups(records: Sequence[ImageRecord], near_dup_hamming: int = 10,
                  sequence_pattern: str | None = None) -> dict[str, list[ImageRecord]]:
    pattern = re.compile(sequence_pattern) if sequence_pattern else None
    n = len(records)
    uf = _UnionFind(n)
    by_key: dict[tuple[str, str], int] = {}
    by_sha: dict[str, int] = {}
    for i, r in enumerate(records):
        k = (r.source_id, base_name(r.rel_path, pattern))
        if k in by_key:
            uf.union(by_key[k], i)
        else:
            by_key[k] = i
        if r.sha256:
            if r.sha256 in by_sha:
                uf.union(by_sha[r.sha256], i)
            else:
                by_sha[r.sha256] = i
    idx = [i for i, r in enumerate(records) if r.phash is not None]
    if len(idx) > 1:
        arr = np.array([records[i].phash for i in idx], dtype=np.uint64)
        for a in range(len(idx) - 1):
            for off in np.nonzero(hamming_matrix_row(arr, a) <= near_dup_hamming)[0]:
                uf.union(idx[a], idx[a + 1 + int(off)])
    groups: dict[str, list[ImageRecord]] = defaultdict(list)
    for i, r in enumerate(records):
        root = records[uf.find(i)]
        groups[f"g:{record_key(root)}"].append(r)
    for gid, members in groups.items():
        for r in members:
            r.group_key = gid
    return groups


@dataclass
class SplitResult:
    assignment: dict[str, str]  # record_key -> split
    class_counts: dict[str, dict[str, int]]
    image_counts: dict[str, int]


def _classes(members: Sequence[ImageRecord]) -> Counter[str]:
    c: Counter[str] = Counter()
    for r in members:
        for b in r.boxes:
            if b.canonical and b.mapping_status == "direct":
                c[b.canonical] += 1
    return c


def make_splits(records: Sequence[ImageRecord], ratios: tuple[float, float, float] = (0.8, 0.1, 0.1),
                holdout_sources: set[str] | None = None, seed: int = 42,
                near_dup_hamming: int = 10, sequence_pattern: str | None = None) -> SplitResult:
    if abs(sum(ratios) - 1.0) > 1e-6:
        raise ValueError("las proporciones deben sumar 1")
    holdout_sources = holdout_sources or set()
    groups = assign_groups(records, near_dup_hamming, sequence_pattern)
    assignment: dict[str, str] = {}
    pool: list[list[ImageRecord]] = []
    for members in groups.values():
        if any(r.source_id in holdout_sources for r in members):
            # Si un holdout comparte grupo con datos públicos, todo el grupo va a test.
            for r in members:
                assignment[record_key(r)] = "test"
        else:
            pool.append(members)

    total = Counter()
    for g in pool:
        total.update(_classes(g))
    total_imgs = sum(len(g) for g in pool)
    target = {s: {c: total[c] * ratios[k] for c in total} for k, s in enumerate(SPLITS)}
    target_imgs = {s: total_imgs * ratios[k] for k, s in enumerate(SPLITS)}
    current = {s: Counter() for s in SPLITS}
    current_imgs = Counter()

    rng = random.Random(seed)
    rng.shuffle(pool)
    # Primero los grupos con clases raras: así se reparten antes de que se llenen las particiones.
    rarity = {c: 1.0 / max(1, n) for c, n in total.items()}
    pool.sort(key=lambda g: -sum(rarity[c] for c in _classes(g)))

    for g in pool:
        cls = _classes(g)
        best, best_score = "train", -float("inf")
        for s in SPLITS:
            if target_imgs[s] == 0:
                continue
            score = (target_imgs[s] - current_imgs[s]) / target_imgs[s]
            for c in cls:
                if target[s][c] > 0:
                    score += (target[s][c] - current[s][c]) / target[s][c]
            if score > best_score:
                best, best_score = s, score
        for r in g:
            assignment[record_key(r)] = best
        current[best].update(cls)
        current_imgs[best] += len(g)

    class_counts = {s: {} for s in SPLITS}
    image_counts = Counter()
    by_key = {record_key(r): r for r in records}
    for k, s in assignment.items():
        image_counts[s] += 1
        for c, n in _classes([by_key[k]]).items():
            class_counts[s][c] = class_counts[s].get(c, 0) + n
    return SplitResult(assignment, class_counts, dict(image_counts))


def find_leakage(records: Sequence[ImageRecord], assignment: dict[str, str], max_hamming: int = 10
                 ) -> list[tuple[str, str]]:
    """Pares exactos o casi idénticos que han quedado en particiones distintas."""
    leaks = []
    hashed = [r for r in records if r.phash is not None and record_key(r) in assignment]
    if len(hashed) < 2:
        return leaks
    arr = np.array([r.phash for r in hashed], dtype=np.uint64)
    for i in range(len(hashed) - 1):
        for off in np.nonzero(hamming_matrix_row(arr, i) <= max_hamming)[0]:
            a, b = hashed[i], hashed[i + 1 + int(off)]
            if assignment[record_key(a)] != assignment[record_key(b)]:
                leaks.append((record_key(a), record_key(b)))
    return leaks
