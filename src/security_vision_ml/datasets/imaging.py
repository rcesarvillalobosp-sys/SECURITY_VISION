"""Lectura de metadatos de imagen y hashes (exacto y perceptual) sin dependencias extra."""

from __future__ import annotations

import hashlib
from functools import cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from .records import ImageRecord, Issue, Severity

PHASH_SIZE = 32
PHASH_LOW = 8


@cache
def _dct_matrix(n: int) -> np.ndarray:
    k = np.arange(n)[:, None]
    i = np.arange(n)[None, :]
    m = np.cos(np.pi * (2 * i + 1) * k / (2 * n)) * np.sqrt(2 / n)
    m[0, :] = np.sqrt(1 / n)
    return m


def phash(img: Image.Image) -> int:
    """pHash de 64 bits: DCT 32x32 en escala de grises, 8x8 de baja frecuencia vs. mediana."""
    gray = img.convert("L").resize((PHASH_SIZE, PHASH_SIZE), Image.Resampling.LANCZOS)
    a = np.asarray(gray, dtype=np.float64)
    d = _dct_matrix(PHASH_SIZE)
    coeffs = (d @ a @ d.T)[:PHASH_LOW, :PHASH_LOW].flatten()
    bits = coeffs > np.median(coeffs[1:])
    value = 0
    for b in bits:
        value = (value << 1) | int(b)
    return value


def inspect_image(record: ImageRecord) -> None:
    """Rellena tamaño, sha256 y pHash. Registra imágenes corruptas como error."""
    path = Path(record.abs_path)
    try:
        data = path.read_bytes()
        record.sha256 = hashlib.sha256(data).hexdigest()
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            record.width, record.height = im.size
            record.phash = phash(im)
    except (OSError, ValueError) as exc:
        record.issues.append(Issue("corrupt_image", Severity.ERROR, str(exc)[:120]))


def hamming_matrix_row(hashes: np.ndarray, i: int) -> np.ndarray:
    """Distancias de Hamming entre hashes[i] y hashes[i+1:] (uint64)."""
    return np.bitwise_count(hashes[i + 1 :] ^ hashes[i]).astype(np.int32)
