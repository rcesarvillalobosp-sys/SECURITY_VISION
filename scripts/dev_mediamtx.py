"""MediaMTX nativo (sin Docker): genera su configuración y lo ejecuta.

    uv run python scripts/dev_mediamtx.py config            # solo este equipo (127.0.0.1)
    uv run python scripts/dev_mediamtx.py config --lan --origin http://192.168.1.20:8000
                                                             # vídeo WebRTC accesible desde la red local
    uv run python scripts/dev_mediamtx.py run                # ejecuta MediaMTX en primer plano

Seguridad (Fase 10):
- **Autenticación HTTP contra la API** (``authMethod: http``): MediaMTX pregunta a la API antes de cada
  acción. Publicar y leer por RTSP requieren el usuario de publicación (worker); la API de control, su
  usuario; un navegador lee por WebRTC con el **token de su sesión web** (permiso ``cameras:read``) y solo
  rutas de cámaras existentes. La API se protege con una clave compartida (``SV_MEDIAMTX_AUTH_KEY``).
- Solo se habilitan RTSP (127.0.0.1) y WebRTC. RTMP, HLS, SRT, **MoQ** (activo por defecto desde MediaMTX
  1.21, escucha en todas las interfaces), métricas, pprof y grabación quedan apagados.
- ``--auth internal`` mantiene el modo anterior (lectura anónima solo desde localhost), sin depender de la API.
"""

from __future__ import annotations

import argparse
import os
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))
from dev_postgres import DEFAULT_BASE, read_env, write_env

MTX_HOME = Path(os.environ.get("SV_MEDIAMTX_HOME") or read_env().get("SV_MEDIAMTX_HOME")
                or DEFAULT_BASE / "mediamtx")


def render_config(*, rtsp_port: int, webrtc_port: int, api_port: int, publish_user: str, publish_pwd: str,
                  api_user: str, api_pwd: str, ice_udp_port: int = 8189, auth: str = "http",
                  auth_url: str | None = None, lan: bool = False, origins: list[str] | None = None,
                  additional_hosts: list[str] | None = None) -> str:
    webrtc_host = "" if lan else "127.0.0.1"
    origins = origins or ["http://localhost:5173", "http://127.0.0.1:5173"]
    if auth == "http":
        if not auth_url:
            raise ValueError("auth http necesita la URL de autorización de la API")
        auth_block = f"""authMethod: http
authHTTPAddress: {auth_url}
authHTTPExclude: []
"""
    else:
        auth_block = f"""authMethod: internal
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
"""
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
moq: no
webrtc: yes
webrtcAddress: {webrtc_host}:{webrtc_port}
webrtcLocalUDPAddress: {webrtc_host}:{ice_udp_port}
webrtcAllowOrigins: {origins!r}
webrtcAdditionalHosts: {additional_hosts or []!r}
{auth_block}paths:
  all_others:
"""


def cmd_config(args: argparse.Namespace) -> None:
    env = read_env()
    pub_pwd = env.get("SV_MEDIAMTX_PUBLISH_PASSWORD") or secrets.token_urlsafe(18)
    api_pwd = env.get("SV_MEDIAMTX_API_PASSWORD") or secrets.token_urlsafe(18)
    auth_key = env.get("SV_MEDIAMTX_AUTH_KEY") or secrets.token_urlsafe(32)
    auth_url = f"{args.api_url.rstrip('/')}/api/v1/media/auth?key={quote(auth_key, safe='')}"
    origins = args.origin or (["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8000",
                               "http://127.0.0.1:8000"])
    cfg = render_config(rtsp_port=8554, webrtc_port=8889, api_port=9997, publish_user="svpublisher",
                        publish_pwd=pub_pwd, api_user="svapi", api_pwd=api_pwd, auth=args.auth, auth_url=auth_url,
                        lan=args.lan, origins=origins, additional_hosts=args.host)
    MTX_HOME.mkdir(parents=True, exist_ok=True)
    out = MTX_HOME / "security-vision.yml"
    out.write_text(cfg, encoding="utf-8")
    updates = {"SV_MEDIAMTX_HOME": str(MTX_HOME), "SV_MEDIAMTX_API_URL": "http://127.0.0.1:9997",
               "SV_MEDIAMTX_RTSP_URL": "rtsp://127.0.0.1:8554",
               "SV_MEDIAMTX_API_USER": "svapi", "SV_MEDIAMTX_API_PASSWORD": api_pwd,
               "SV_MEDIAMTX_PUBLISH_USER": "svpublisher", "SV_MEDIAMTX_PUBLISH_PASSWORD": pub_pwd,
               "SV_MEDIAMTX_AUTH_KEY": auth_key}
    # URL WebRTC que reciben los navegadores: la del equipo si se sirve a la red local
    updates["SV_MEDIAMTX_WEBRTC_URL"] = args.public_webrtc_url or "http://127.0.0.1:8889"
    write_env(updates)
    print(f"Configuración ({args.auth}{', red local' if args.lan else ', solo este equipo'}) escrita en {out}; "
          "credenciales en .env")


def cmd_run(_: argparse.Namespace) -> None:
    exe = MTX_HOME / ("mediamtx.exe" if sys.platform.startswith("win") else "mediamtx")
    cfg = MTX_HOME / "security-vision.yml"
    if not cfg.exists():
        sys.exit("Ejecuta primero: scripts/dev_mediamtx.py config")
    # cwd = carpeta de MediaMTX: cualquier archivo que genere (p. ej. certificados) queda ahí, no en el repo
    sys.exit(subprocess.call([str(exe), str(cfg)], cwd=MTX_HOME))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("config")
    c.add_argument("--auth", choices=["http", "internal"], default="http")
    c.add_argument("--api-url", default="http://127.0.0.1:8000", help="URL de la API vista desde MediaMTX")
    c.add_argument("--lan", action="store_true", help="WebRTC en todas las interfaces (RTSP sigue en 127.0.0.1)")
    c.add_argument("--origin", action="append", help="origen web permitido (repetible), p. ej. http://192.168.1.20:8000")
    c.add_argument("--host", action="append", help="IP/nombre adicional anunciado a los navegadores (ICE)")
    c.add_argument("--public-webrtc-url", help="URL WebRTC para los navegadores, p. ej. http://192.168.1.20:8889")
    sub.add_parser("run")
    args = ap.parse_args()
    {"config": cmd_config, "run": cmd_run}[args.cmd](args)


if __name__ == "__main__":
    main()
