"""Simulador de N cámaras IP para pruebas de carga: publica un vídeo en bucle por RTSP en MediaMTX.

Copia los paquetes ya codificados (sin decodificar ni recodificar), al ritmo real de sus marcas de
tiempo: el coste de CPU del simulador es mínimo y no contamina la medida del worker. Cada cámara
arranca desplazada en el vídeo para que no analicen todas la misma imagen a la vez.

    uv run python scripts/rtsp_simulator.py --cameras 4            # rtsp://127.0.0.1:8554/sim-0..3
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

import av

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def publish(idx: int, video: Path, base_url: str, user: str | None, pwd: str | None, stop: threading.Event,
            offset_s: float) -> None:
    auth = f"{user}:{pwd}@" if user and pwd else ""
    url = base_url.replace("rtsp://", f"rtsp://{auth}") + f"/sim-{idx}"
    while not stop.is_set():
        try:
            inp = av.open(str(video))
            ist = inp.streams.video[0]
            out = av.open(url, "w", format="rtsp", options={"rtsp_transport": "tcp"})
            ost = out.add_stream_from_template(ist)
            tb = float(ist.time_base)
            dur = float(inp.duration or 0) / 1e6 or 60.0
            loop_offset = 0  # en unidades de time_base
            t0 = time.monotonic() - offset_s
            first = True
            while not stop.is_set():
                inp.seek(0)
                last_pts = 0
                for pkt in inp.demux(ist):
                    if pkt.dts is None or stop.is_set():
                        continue
                    pts_s = (pkt.pts or 0) * tb + loop_offset * tb
                    if first and pts_s < offset_s:  # arranque desplazado: salta hasta el keyframe del offset
                        if not pkt.is_keyframe or pts_s < offset_s - 2:
                            continue
                        t0 = time.monotonic() - pts_s
                    first = False
                    wait = t0 + pts_s - time.monotonic()
                    if wait > 0:
                        time.sleep(wait)
                    last_pts = pkt.pts or last_pts
                    pkt.pts = (pkt.pts or 0) + loop_offset
                    pkt.dts = pkt.dts + loop_offset
                    pkt.stream = ost
                    out.mux(pkt)
                loop_offset += round(dur / tb)
            out.close()
            inp.close()
        except Exception as exc:  # MediaMTX reiniciado, etc.: reintenta
            print(f"sim-{idx}: {type(exc).__name__}: {exc}; reintento en 2 s", flush=True)
            time.sleep(2)


def main() -> None:
    from security_vision.core.configuration.settings import get_settings

    ap = argparse.ArgumentParser()
    ap.add_argument("--cameras", type=int, required=True)
    ap.add_argument("--video", type=Path, default=ROOT / "var/videos/load_1080p15.mp4")
    a = ap.parse_args()
    s = get_settings()
    pwd = s.mediamtx_publish_password.get_secret_value() if s.mediamtx_publish_password else None
    stop = threading.Event()
    threads = [threading.Thread(target=publish, args=(i, a.video, s.mediamtx_rtsp_url, s.mediamtx_publish_user, pwd,
                                                      stop, (i * 7.3) % 50), daemon=True)
               for i in range(a.cameras)]
    for t in threads:
        t.start()
    print(f"publicando {a.cameras} cámaras simuladas en {s.mediamtx_rtsp_url}/sim-N", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
