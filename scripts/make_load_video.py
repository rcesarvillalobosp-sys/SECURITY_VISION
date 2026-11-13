"""Genera el vídeo de las pruebas de carga: 1080p, 15 fps, MPEG-4 Part 2 (codificador nativo de FFmpeg, LGPL).

Se construye a partir de un vídeo de imágenes reales de EPP (por defecto ``var/videos/ppe_val_slideshow.mp4``)
escalado a 1920x1080 y con un ligero desplazamiento por fotograma para que el códec no reciba imágenes
idénticas (un vídeo estático se decodifica de forma irrealmente barata). NO usa libx264 (GPL, ADR-0010).
Para WebRTC: ``--codec h264_nvenc`` (codificador por hardware de NVIDIA).

    uv run python scripts/make_load_video.py --seconds 60
"""

from __future__ import annotations

import argparse
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, default=ROOT / "var/videos/ppe_val_slideshow.mp4")
    ap.add_argument("--out", type=Path, default=ROOT / "var/videos/load_1080p15.mp4")
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--bitrate", type=int, default=4_000_000)
    ap.add_argument("--codec", default="mpeg4", choices=["mpeg4", "h264_nvenc", "h264_mf"],
                    help="h264_nvenc/h264_mf: H.264 por hardware (NVIDIA) o Media Foundation, sin GPL; "
                         "necesario para ver el vídeo por WebRTC en el navegador")
    a = ap.parse_args()

    src = av.open(str(a.source))
    images = [f.to_ndarray(format="rgb24") for f in src.decode(video=0)]
    src.close()
    if not images:
        raise SystemExit("el vídeo de origen no tiene fotogramas")

    out = av.open(str(a.out), "w")
    opts = {"bf": "0", "profile": "baseline"} if a.codec == "h264_nvenc" else {}
    st = out.add_stream(a.codec, rate=a.fps, options=opts)
    st.width, st.height, st.pix_fmt = 1920, 1080, "yuv420p"
    st.bit_rate = a.bitrate
    st.codec_context.gop_size = a.fps * 2  # un fotograma clave cada 2 s, como una cámara IP típica
    st.time_base = Fraction(1, a.fps)
    n = a.seconds * a.fps
    per_image = max(1, n // len(images))
    for i in range(n):
        base = Image.fromarray(images[(i // per_image) % len(images)]).resize((1960, 1104), Image.Resampling.BILINEAR)
        dx, dy = (i % per_image) % 40, (i % per_image) % 24  # desplazamiento lento (cámara que "respira")
        arr = np.asarray(base)[dy:dy + 1080, dx:dx + 1920]
        frame = av.VideoFrame.from_ndarray(np.ascontiguousarray(arr), format="rgb24")
        frame.pts = i
        for p in st.encode(frame):
            out.mux(p)
    for p in st.encode():
        out.mux(p)
    out.close()
    size = a.out.stat().st_size
    print(f"{a.out} · {n} fotogramas · {a.seconds} s · {size / 1e6:.1f} MB · {size * 8 / a.seconds / 1e6:.2f} Mbit/s")


if __name__ == "__main__":
    main()
