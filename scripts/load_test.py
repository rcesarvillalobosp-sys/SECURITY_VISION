"""Prueba de carga del sistema real: N cámaras RTSP simuladas -> MediaMTX -> worker (detección, tracking,
reglas, evidencias) -> API. Mide lo que el sistema hace de verdad; no estima nada.

Requisitos en marcha: PostgreSQL, MediaMTX, API (``svctl serve``), worker (``sv-worker``) y el simulador
(``scripts/rtsp_simulator.py --cameras N``, que publica ``sim-0..N-1``).

    uv run python scripts/load_test.py --cameras 1 2 4 6 --analysis-fps 2 --duration 60 --label base

Para cada N: crea N cámaras, espera el calentamiento, muestrea cada 2 s las métricas del worker
(``/metrics``), la CPU/RAM del sistema y de cada proceso, y la GPU (``nvidia-smi``); después borra las
cámaras. Resultado en ``ml/evaluation/results/load_<label>_<fecha>.json``.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psutil
from prometheus_client.parser import text_string_to_metric_families

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
API = "http://127.0.0.1:8000"
METRICS = "http://127.0.0.1:9101/metrics"


def scrape() -> dict[str, list[tuple[dict[str, str], float]]]:
    text = httpx.get(METRICS, timeout=5).text
    out: dict[str, list[tuple[dict[str, str], float]]] = {}
    for fam in text_string_to_metric_families(text):
        for s in fam.samples:
            out.setdefault(s.name, []).append((dict(s.labels), s.value))
    return out


def by_camera(m: dict, name: str, cams: set[str]) -> dict[str, float]:
    return {lab["camera_id"]: v for lab, v in m.get(name, []) if lab.get("camera_id") in cams}


def gpu() -> dict[str, float] | None:
    if not shutil.which("nvidia-smi"):
        return None
    r = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,temperature.gpu,power.draw",
                        "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5)
    if r.returncode:
        return None
    u, mem, t, p = (x.strip() for x in r.stdout.splitlines()[0].split(","))
    return {"util_pct": float(u), "mem_mb": float(mem), "temp_c": float(t),
            "power_w": float(p) if p not in ("[N/A]", "") else None}


def find_procs() -> dict[str, psutil.Process]:
    found: dict[str, psutil.Process] = {}
    for p in psutil.process_iter(["name", "cmdline"]):
        cmd = " ".join(p.info["cmdline"] or []).lower()
        name = (p.info["name"] or "").lower()
        if "sv-worker" in cmd and "worker" not in found:
            found["worker"] = p
        elif "mediamtx" in name:
            found["mediamtx"] = p
        elif "rtsp_simulator" in cmd:
            found["simulator"] = p
        elif "svctl" in cmd and "serve" in cmd:
            found["api"] = p
    # sv-worker.exe lanza el intérprete como proceso hijo: se mide el que más memoria usa
    if "worker" in found:
        fam = [found["worker"], *found["worker"].children(recursive=True)]
        found["worker"] = max(fam, key=lambda q: q.memory_info().rss)
    return found


def sim_credentials() -> dict[str, str]:
    """Las cámaras simuladas se publican en el propio MediaMTX: se leen con credenciales (como una cámara
    IP real), necesarias con la autorización HTTP de MediaMTX (Fase 10)."""
    from security_vision.core.configuration.settings import get_settings

    s = get_settings()
    if s.mediamtx_publish_user and s.mediamtx_publish_password:
        return {"username": s.mediamtx_publish_user, "password": s.mediamtx_publish_password.get_secret_value()}
    return {}


def stages(m: dict) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for lab, v in m.get("sv_stage_ms", []):
        q = {"0.5": "p50", "0.95": "p95"}.get(lab["quantile"], lab["quantile"])
        out.setdefault(lab["stage"], {})[q] = round(v, 2)
    return out


def gpu_name() -> str | None:
    if not shutil.which("nvidia-smi"):
        return None
    return subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
                          capture_output=True, text=True).stdout.strip()


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    return v[min(len(v) - 1, round(q * (len(v) - 1)))]


def run_level(client: httpx.Client, h: dict, n: int, fps: float, warmup: float, duration: float,
              profile_id: str | None) -> dict:
    cams = []
    for i in range(n):
        r = client.post("/api/v1/cameras", headers=h, json={
            "name": f"carga-{i}", "source_type": "rtsp", "source_uri": f"rtsp://127.0.0.1:8554/sim-{i}",
            "analysis_fps": fps, "default_profile_id": profile_id, **sim_credentials()})
        r.raise_for_status()
        cams.append(r.json()["id"])
    ids = set(cams)
    try:
        time.sleep(warmup)
        procs = find_procs()
        for p in procs.values():
            p.cpu_percent(None)
        psutil.cpu_percent(None)
        m0, t0 = scrape(), time.monotonic()
        samples: list[dict] = []
        while time.monotonic() - t0 < duration:
            time.sleep(2)
            m = scrape()
            ages = by_camera(m, "sv_analysis_frame_age_seconds", ids)
            samples.append({
                "cpu_total_pct": psutil.cpu_percent(None),
                "ram_used_mb": psutil.virtual_memory().used / 2**20,
                "procs": {k: {"cpu_pct": p.cpu_percent(None), "rss_mb": p.memory_info().rss / 2**20}
                          for k, p in procs.items() if p.is_running()},
                "gpu": gpu(),
                "frame_age_s": ages,
                "up": by_camera(m, "sv_camera_up", ids),
            })
        m1, t1 = scrape(), time.monotonic()
        dt = t1 - t0

        def delta(name: str) -> dict[str, float]:
            a, b = by_camera(m0, name, ids), by_camera(m1, name, ids)
            return {c: b.get(c, 0) - a.get(c, 0) for c in ids}

        th0 = {lab["group"]: v for lab, v in m0.get("sv_worker_thread_cpu_seconds_total", [])}
        th1 = {lab["group"]: v for lab, v in m1.get("sv_worker_thread_cpu_seconds_total", [])}
        # % de un núcleo por grupo de hilos durante el nivel (hilos que terminan entre medias se pierden)
        threads_cpu = {g: round(100 * (v - th0.get(g, 0.0)) / (t1 - t0), 1) for g, v in th1.items()}
        analyzed = delta("sv_analysis_frames_total")
        captured = delta("sv_camera_frames_total")
        dropped = delta("sv_camera_frames_dropped_total")
        inf = {lab["quantile"]: v for lab, v in m1.get("sv_inference_ms", [])}
        calls0 = sum(v for _, v in m0.get("sv_inference_calls_total", []))
        calls1 = sum(v for _, v in m1.get("sv_inference_calls_total", []))
        per_cam_fps = [analyzed[c] / dt for c in cams]
        ages_all = [a for s in samples for c, a in s["frame_age_s"].items()]
        g = [s["gpu"] for s in samples if s["gpu"]]

        def proc_stat(key: str, field: str) -> dict[str, float | None]:
            vals = [s["procs"][key][field] for s in samples if key in s["procs"]]
            return {"mean": statistics.fmean(vals) if vals else None, "max": max(vals) if vals else None}

        return {
            "cameras": n, "analysis_fps_target": fps, "duration_s": round(dt, 1),
            "analysis_fps_per_camera": {"mean": statistics.fmean(per_cam_fps), "min": min(per_cam_fps),
                                        "max": max(per_cam_fps)},
            "analysis_fps_total": sum(per_cam_fps),
            "target_met": min(per_cam_fps) >= 0.95 * fps,
            "capture_fps_per_camera": statistics.fmean([captured[c] / dt for c in cams]),
            "frames_dropped_slot_per_s": sum(dropped.values()) / dt,
            "frame_age_s": {"p50": pct(ages_all, 0.5), "p95": pct(ages_all, 0.95), "max": max(ages_all or [0])},
            "inference_ms": {"p50": inf.get("0.5"), "p95": inf.get("0.95")},
            "inference_calls_per_s": (calls1 - calls0) / dt,
            "cameras_up_min": min((sum(s["up"].values()) for s in samples), default=0),
            "cpu_total_pct": {"mean": statistics.fmean(s["cpu_total_pct"] for s in samples),
                              "max": max(s["cpu_total_pct"] for s in samples)},
            "ram_used_mb_max": max(s["ram_used_mb"] for s in samples),
            "worker": {"cpu_pct": proc_stat("worker", "cpu_pct"), "rss_mb": proc_stat("worker", "rss_mb")},
            "mediamtx": {"cpu_pct": proc_stat("mediamtx", "cpu_pct"), "rss_mb": proc_stat("mediamtx", "rss_mb")},
            "simulator": {"cpu_pct": proc_stat("simulator", "cpu_pct")},
            "api": {"cpu_pct": proc_stat("api", "cpu_pct"), "rss_mb": proc_stat("api", "rss_mb")},
            "gpu": {"util_pct_mean": statistics.fmean(x["util_pct"] for x in g) if g else None,
                    "util_pct_max": max(x["util_pct"] for x in g) if g else None,
                    "mem_mb_max": max(x["mem_mb"] for x in g) if g else None,
                    "temp_c_max": max(x["temp_c"] for x in g) if g else None},
            "samples": len(samples),
            # Tiempos por etapa del worker en los últimos 60 s (= este nivel): ms
            "stages_ms": stages(m1),
            "worker_threads_cpu_pct": threads_cpu,
        }
    finally:
        for c in cams:
            client.delete(f"/api/v1/cameras/{c}", headers=h)
        time.sleep(3)


def main() -> None:
    from security_vision.core.configuration.settings import get_settings

    ap = argparse.ArgumentParser()
    ap.add_argument("--cameras", type=int, nargs="+", required=True)
    ap.add_argument("--analysis-fps", type=float, default=2.0)
    ap.add_argument("--warmup", type=float, default=20.0)
    ap.add_argument("--duration", type=float, default=60.0)
    ap.add_argument("--label", default="run")
    ap.add_argument("--notes", default="")
    ap.add_argument("--video-desc",
                    default="var/videos/load_1080p15.mp4 (1920x1080, 15 fps, MPEG-4 Part 2, ~3.3 Mbit/s)")
    a = ap.parse_args()
    s = get_settings()
    if not (s.bootstrap_admin_email and s.bootstrap_admin_password):
        raise SystemExit("se necesitan SV_BOOTSTRAP_ADMIN_EMAIL/PASSWORD en .env para crear las cámaras de prueba")
    client = httpx.Client(base_url=API, timeout=30)
    tok = client.post("/api/v1/auth/login", json={"email": s.bootstrap_admin_email,
                                                  "password": s.bootstrap_admin_password.get_secret_value()})
    tok.raise_for_status()
    h = {"Authorization": f"Bearer {tok.json()['access_token']}"}
    if [c for c in client.get("/api/v1/cameras", headers=h).json() if c["enabled"]]:
        raise SystemExit("hay cámaras habilitadas: la prueba necesita el worker sin otras cámaras")
    profiles = client.get("/api/v1/security-profiles", headers=h).json()
    profile_id = profiles[0]["id"] if profiles else None
    models = client.get("/api/v1/models", headers=h).json()
    results = {
        "label": a.label, "notes": a.notes, "started_at": datetime.now(UTC).isoformat(),
        "host": {"cpu": platform.processor(), "logical_cpus": psutil.cpu_count(),
                 "ram_gb": round(psutil.virtual_memory().total / 2**30, 1), "os": platform.platform(),
                 "gpu": gpu_name()},
        "model_loaded": models.get("loaded"), "engine": s.inference_engine, "devices": s.inference_devices,
        "video": f"{a.video_desc} vía RTSP/MediaMTX",
        "levels": [],
    }
    for n in a.cameras:
        print(f"== {n} cámara(s) a {a.analysis_fps} fps de análisis...", flush=True)
        r = run_level(client, h, n, a.analysis_fps, a.warmup, a.duration, profile_id)
        results["levels"].append(r)
        fpc = r["analysis_fps_per_camera"]
        print(f"   análisis/cámara {fpc['mean']:.2f} (mín {fpc['min']:.2f}) "
              f"· edad p95 {r['frame_age_s']['p95']} s · inferencia p50 {r['inference_ms']['p50']} ms "
              f"· CPU {r['cpu_total_pct']['mean']:.0f}% · GPU {r['gpu']['util_pct_mean']}% · objetivo "
              f"{'OK' if r['target_met'] else 'NO'}", flush=True)
    out = ROOT / "ml/evaluation/results" / f"load_{a.label}_{datetime.now(UTC):%Y%m%dT%H%M%S}.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
