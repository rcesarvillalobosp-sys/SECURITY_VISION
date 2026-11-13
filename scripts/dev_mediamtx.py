"""MediaMTX local de desarrollo (binario nativo, sin Docker).

    uv run python scripts/dev_mediamtx.py config   # genera la configuración y credenciales (.env)
    uv run python scripts/dev_mediamtx.py run      # ejecuta MediaMTX en primer plano

Seguridad: todo escucha en 127.0.0.1; la API de control y la publicación requieren usuario;
la lectura (RTSP/WebRTC) se permite solo desde localhost.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from dev_postgres import DEFAULT_BASE, read_env, write_env

MTX_HOME = Path(os.environ.get("SV_MEDIAMTX_HOME") or read_env().get("SV_MEDIAMTX_HOME")
                or DEFAULT_BASE / "mediamtx")


def render_config(*, rtsp_port: int, webrtc_port: int, api_port: int, publish_user: str, publish_pwd: str,
                  api_user: str, api_pwd: str, ice_udp_port: int = 8189) -> str:
    return f"""# Generado por scripts/dev_mediamtx.py — no editar a mano.
logLevel: info
logDestinations: [stdout]
api: yes
apiAddress: 127.0.0.1:{api_port}
metrics: no
pprof: no
playback: no
rtsp: yes
rtspAddress: 127.0.0.1:{rtsp_port}
rtspTransports: [tcp]
rtmp: no
hls: no
srt: no
webrtc: yes
webrtcAddress: 127.0.0.1:{webrtc_port}
webrtcLocalUDPAddress: 127.0.0.1:{ice_udp_port}
webrtcAllowOrigins: ['http://localhost:5173', 'http://127.0.0.1:5173']
authMethod: internal
authInternalUsers:
  - user: {publish_user}
    pass: {publish_pwd}
    ips: ['127.0.0.1', '::1']
    permissions:
      - action: publish
      - action: read
  - user: {api_user}
    pass: {api_pwd}
    ips: ['127.0.0.1', '::1']
    permissions:
      - action: api
  - user: any
    pass:
    ips: ['127.0.0.1', '::1']
    permissions:
      - action: read
paths:
  all_others:
"""


def cmd_config() -> None:
    env = read_env()
    pub_pwd = env.get("SV_MEDIAMTX_PUBLISH_PASSWORD") or secrets.token_urlsafe(18)
    api_pwd = env.get("SV_MEDIAMTX_API_PASSWORD") or secrets.token_urlsafe(18)
    cfg = render_config(rtsp_port=8554, webrtc_port=8889, api_port=9997, publish_user="svpublisher",
                        publish_pwd=pub_pwd, api_user="svapi", api_pwd=api_pwd)
    out = MTX_HOME / "security-vision.yml"
    out.write_text(cfg, encoding="utf-8")
    write_env({"SV_MEDIAMTX_HOME": str(MTX_HOME), "SV_MEDIAMTX_API_URL": "http://127.0.0.1:9997",
               "SV_MEDIAMTX_RTSP_URL": "rtsp://127.0.0.1:8554", "SV_MEDIAMTX_WEBRTC_URL": "http://127.0.0.1:8889",
               "SV_MEDIAMTX_API_USER": "svapi", "SV_MEDIAMTX_API_PASSWORD": api_pwd,
               "SV_MEDIAMTX_PUBLISH_USER": "svpublisher", "SV_MEDIAMTX_PUBLISH_PASSWORD": pub_pwd})
    print(f"Configuración escrita en {out}; credenciales en .env")


def cmd_run() -> None:
    exe = MTX_HOME / ("mediamtx.exe" if sys.platform.startswith("win") else "mediamtx")
    cfg = MTX_HOME / "security-vision.yml"
    if not cfg.exists():
        sys.exit("Ejecuta primero: scripts/dev_mediamtx.py config")
    sys.exit(subprocess.call([str(exe), str(cfg)]))


if __name__ == "__main__":
    cmds = {"config": cmd_config, "run": cmd_run}
    if len(sys.argv) != 2 or sys.argv[1] not in cmds:
        sys.exit("uso: dev_mediamtx.py {config|run}")
    cmds[sys.argv[1]]()
