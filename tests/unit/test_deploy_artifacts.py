"""Coherencia de los artefactos de despliegue (sin Docker en este equipo no se pueden construir: aquí se
verifica todo lo que se puede comprobar de forma estática)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _compose() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def test_compose_files_and_build_contexts_exist():
    c = _compose()
    for name, svc in c["services"].items():
        if "build" in svc:
            assert (ROOT / svc["build"]["dockerfile"]).is_file(), name
        for vol in svc.get("volumes", []):
            src = vol.split(":")[0]
            if src.startswith("./"):
                assert (ROOT / src).exists(), f"{name}: falta {src}"
    gpu = yaml.safe_load((ROOT / "docker-compose.gpu.yml").read_text(encoding="utf-8"))
    assert set(gpu["services"]) <= set(c["services"])


def test_required_compose_variables_are_documented():
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    required = set(re.findall(r"\$\{(\w+):\?", text))
    documented = set(re.findall(r"^#?\s*(SV_\w+)=", (ROOT / ".env.example").read_text(encoding="utf-8"), re.M))
    assert required and required <= documented, required - documented


def test_dockerfile_copies_existing_paths_and_pins_images():
    df = (ROOT / "docker/app.Dockerfile").read_text(encoding="utf-8")
    for line in df.splitlines():
        if line.startswith("COPY") and "--from" not in line:
            for src in line.split()[1:-1]:
                assert (ROOT / src).exists() or (ROOT / "apps/web" / src).exists(), src
        if line.startswith("FROM") or "COPY --from=" in line:
            image = line.split()[1].split("=")[-1]
            if ":" in image:
                assert not image.endswith(":latest"), line
    assert {"AS api", "AS worker", "AS web"} <= {m.group(0) for m in re.finditer(r"AS \w+", df)}
    assert "USER sv" in df  # nunca como root
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    for must in (".env", ".venv", "ml/datasets", "var", ".git"):
        assert must in ignore.splitlines(), must


def _assert_hardened(cfg: dict) -> None:
    for proto in ("rtmp", "hls", "srt", "moq", "metrics", "pprof", "playback"):
        assert cfg[proto] is False, proto  # YAML 'no' -> False
    assert cfg["authMethod"] == "http"


def test_mediamtx_configs_are_hardened():
    _assert_hardened(yaml.safe_load((ROOT / "docker/mediamtx/mediamtx.yml").read_text(encoding="utf-8")))
    sys.path.insert(0, str(ROOT / "scripts"))
    from dev_mediamtx import render_config

    native = yaml.safe_load(render_config(rtsp_port=8554, webrtc_port=8889, api_port=9997, publish_user="p",
                                          publish_pwd="x", api_user="a", api_pwd="y",
                                          auth_url="http://127.0.0.1:8000/api/v1/media/auth?key=k"))
    _assert_hardened(native)
    assert native["rtspAddress"].startswith("127.0.0.1") and native["webrtcAddress"].startswith("127.0.0.1")
    lan = yaml.safe_load(render_config(rtsp_port=8554, webrtc_port=8889, api_port=9997, publish_user="p",
                                       publish_pwd="x", api_user="a", api_pwd="y", auth_url="http://x/a",
                                       lan=True))
    assert lan["rtspAddress"].startswith("127.0.0.1")  # RTSP nunca sale del equipo
    assert lan["webrtcAddress"] == ":8889"


def test_monitoring_targets_and_dashboard_metrics_exist():
    prom = yaml.safe_load((ROOT / "docker/prometheus/prometheus.yml").read_text(encoding="utf-8"))
    targets = {t for job in prom["scrape_configs"] for sc in job["static_configs"] for t in sc["targets"]}
    assert targets == {"api:8000", "worker:9101"}
    dash_file = ROOT / "docker/grafana/provisioning/dashboards/security-vision.json"
    dash = json.loads(dash_file.read_text(encoding="utf-8"))
    code = "\n".join(p.read_text(encoding="utf-8") for p in
                     list((ROOT / "apps").rglob("*.py")) + list((ROOT / "src/security_vision").rglob("*.py")))
    for panel in dash["panels"]:
        for t in panel["targets"]:
            for metric in re.findall(r"\b(sv_[a-z_]+)", t["expr"]):
                base = re.sub(r"_(total|bucket|count|sum|created)$", "", metric)
                assert f'"{base}"' in code, f"{panel['title']}: {metric} no lo publica el código"
