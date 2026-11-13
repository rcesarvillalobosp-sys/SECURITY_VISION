"""Medición de captura con N cámaras RTSP SIMULADAS (patrón sintético publicado en MediaMTX).

    uv run python scripts/measure_capture.py --cameras 4 --seconds 60

- Un proceso aparte publica N streams (para que su codificación no contamine las cifras).
- Este proceso los captura con PyAV vía RTSP (como el worker), con un consumidor de análisis por
  cámara a --analysis-fps que mide la antigüedad del fotograma (sin inferencia).
- Limitación: el patrón sintético es muy compresible; el coste de decodificar una cámara real
  (texturas, ruido, mayor bitrate) será mayor. Las cifras sirven como línea base, no como capacidad final.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def publish_mode(rtsp: str, n: int, w: int, h: int, fps: int) -> None:
    import threading

    from security_vision.core.interfaces.video import VideoSourceConfig
    from security_vision.plugins.video_sources.pyav_publisher import PyAVRtspPublisher
    from security_vision.plugins.video_sources.test_pattern import TestPatternSource

    def run(i: int) -> None:
        src = TestPatternSource(VideoSourceConfig(uri=f"testpattern://?width={w}&height={h}&fps={fps}"))
        src.connect()
        pub = PyAVRtspPublisher(f"{rtsp}/sim{i}", fps, "pub", "pub-pass")
        while True:
            pub.publish(src.read_frame(1.0))

    for i in range(n):
        threading.Thread(target=run, args=(i,), daemon=True).start()
    while True:
        time.sleep(1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cameras", type=int, default=4)
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--analysis-fps", type=float, default=2.0)
    ap.add_argument("--publish", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.publish:
        publish_mode(a.publish, a.cameras, a.width, a.height, a.fps)
        return 0

    import psutil
    from dev_mediamtx import MTX_HOME, render_config
    from security_vision_worker.runtime import AnalysisLoop

    from security_vision.core.interfaces.video import VideoSourceConfig
    from security_vision.modules.cameras.supervisor import CameraSpec, CameraSupervisor
    from security_vision.plugins.video_sources.pyav_source import PyAVVideoSource

    ports = {k: free_port() for k in ("rtsp", "webrtc", "api", "ice")}
    cfg = Path(tempfile.mkdtemp()) / "mtx.yml"
    cfg.write_text(render_config(rtsp_port=ports["rtsp"], webrtc_port=ports["webrtc"], api_port=ports["api"],
                                 ice_udp_port=ports["ice"], publish_user="pub", publish_pwd="pub-pass",
                                 api_user="api", api_pwd="api-pass"), encoding="utf-8")
    exe = MTX_HOME / ("mediamtx.exe" if sys.platform.startswith("win") else "mediamtx")
    mtx = subprocess.Popen([str(exe), str(cfg)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rtsp = f"rtsp://127.0.0.1:{ports['rtsp']}"
    time.sleep(1.5)
    pub = subprocess.Popen([sys.executable, __file__, "--publish", rtsp, "--cameras", str(a.cameras),
                            "--width", str(a.width), "--height", str(a.height), "--fps", str(a.fps)])
    time.sleep(4)
    sup = CameraSupervisor(lambda spec: PyAVVideoSource(spec.source))
    loops = []
    proc = psutil.Process()
    try:
        for i in range(a.cameras):
            w = sup.start(CameraSpec(f"sim{i}", f"sim{i}", "pyav", VideoSourceConfig(
                uri=f"{rtsp}/sim{i}", options={"open_timeout": 5, "read_timeout": 5}), analysis_fps=a.analysis_fps))
            loop = AnalysisLoop(w)
            loop.start()
            loops.append(loop)
        time.sleep(5)  # calentamiento
        base = {cid: (w.stats.frames, w.slot.dropped) for cid, w in sup.workers().items()}
        base_an = {lp.worker.spec.camera_id: lp.stats.analyzed for lp in loops}
        proc.cpu_percent(None)
        cpu_samples, rss = [], []
        t0 = time.monotonic()
        while time.monotonic() - t0 < a.seconds:
            time.sleep(1)
            cpu_samples.append(proc.cpu_percent(None))
            rss.append(proc.memory_info().rss)
        elapsed = time.monotonic() - t0
        rows = []
        for lp in loops:
            cid = lp.worker.spec.camera_id
            st = lp.worker.stats
            frames = st.frames - base[cid][0]
            rows.append({
                "camera": cid, "capture_fps": round(frames / elapsed, 2),
                "analysis_fps": round((lp.stats.analyzed - base_an[cid]) / elapsed, 2),
                "dropped_by_backpressure": lp.worker.slot.dropped - base[cid][1],
                "frame_age_ms_ewma": round(lp.stats.frame_age_ewma * 1000, 1),
                "read_errors": st.read_errors, "reconnects": st.reconnects,
                "resolution": f"{st.width}x{st.height}"})
        cores = psutil.cpu_count(logical=True)
        summary = {
            "cameras": a.cameras, "seconds": round(elapsed, 1), "source": f"{a.width}x{a.height}@{a.fps} sintético",
            "capture_process_cpu_percent_avg": round(sum(cpu_samples) / len(cpu_samples), 1),
            "capture_process_cpu_percent_of_machine": round(sum(cpu_samples) / len(cpu_samples) / cores, 1),
            "capture_process_rss_mb_max": round(max(rss) / 2**20, 1), "logical_cores": cores, "per_camera": rows}
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    finally:
        for lp in loops:
            lp.stop()
        sup.stop_all()
        pub.terminate()
        mtx.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
