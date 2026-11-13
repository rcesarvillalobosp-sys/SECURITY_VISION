"""Fuente de vídeo basada en PyAV (FFmpeg): RTSP/RTSPS, archivos y cámaras USB.

USB: DirectShow en Windows (``usb:<nombre>``), V4L2 en Linux (``usb:/dev/video0`` o ``usb:0``),
AVFoundation en macOS (``usb:0``).

Licencia: PyAV es BSD-3. Las ruedas binarias de PyPI incluyen FFmpeg (LGPLv3) y además las
bibliotecas libx264/libx265 (GPL). Este adaptador SOLO decodifica y nunca usa esos codificadores;
para distribuir el producto se debe usar una compilación de PyAV contra un FFmpeg LGPL sin
x264/x265 o el adaptador GStreamer (ver ADR-0010).
"""

from __future__ import annotations

import contextlib
import logging
import sys
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, ClassVar
from urllib.parse import quote, urlsplit, urlunsplit

import av
import av.error
import av.logging

from security_vision.core.interfaces.video import (
    Frame,
    SourceCapabilities,
    SourceMetadata,
    SourceStatus,
    VideoSource,
    VideoSourceConfig,
    VideoSourceError,
)

log = logging.getLogger(__name__)
DEFAULT_OPEN_TIMEOUT = 10.0
DEFAULT_READ_TIMEOUT = 10.0


def _with_credentials(uri: str, username: str | None, password: str | None) -> str:
    if not username:
        return uri
    parts = urlsplit(uri)
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    userinfo = quote(username, safe="") + (":" + quote(password, safe="") if password else "")
    return urlunsplit((parts.scheme, f"{userinfo}@{host}", parts.path, parts.query, parts.fragment))


def usb_input(device: str) -> tuple[str, str]:
    """Traduce ``usb:<dispositivo>`` al par (entrada, formato) de FFmpeg según el SO."""
    if sys.platform.startswith("win"):
        return f"video={device}", "dshow"
    if sys.platform == "darwin":
        return device, "avfoundation"
    return (f"/dev/video{device}" if device.isdigit() else device), "v4l2"


def list_usb_cameras() -> list[str]:
    """Nombres de cámaras DirectShow (Windows). En otros SO devuelve los /dev/video* existentes."""
    if not sys.platform.startswith("win"):
        from pathlib import Path

        return sorted(str(p) for p in Path("/dev").glob("video*"))
    names: list[str] = []
    with av.logging.Capture() as logs, contextlib.suppress(av.error.FFmpegError, OSError):
        av.open("dummy", format="dshow", options={"list_devices": "true"})
    for _level, _name, message in logs:
        # Formato FFmpeg: '"Nombre de la cámara" (video)'
        if "(video)" in message and '"' in message:
            names.append(message.split('"')[1])
    return names


class PyAVVideoSource(VideoSource):
    provider_name: ClassVar[str] = "pyav"

    def __init__(self, config: VideoSourceConfig) -> None:
        super().__init__(config)
        self._container: Any = None
        self._frames: Iterator[Any] | None = None
        self._status = SourceStatus.DISCONNECTED
        self._frame_id = 0
        self._lock = threading.Lock()
        self._meta = SourceMetadata(None, None, None, None)
        self._is_file = False
        self._t0_wall = 0.0
        self._t0_pts: float | None = None

    @classmethod
    def capabilities(cls) -> SourceCapabilities:
        return SourceCapabilities(schemes=frozenset({"rtsp", "rtsps", "file", "usb"}), hardware_decoding=False)

    # ------------------------------------------------------------------ conexión
    def _open_args(self) -> tuple[str, dict[str, Any]]:
        cfg = self.config
        o = cfg.options
        opts: dict[str, str] = {}
        kwargs: dict[str, Any] = {
            "timeout": (float(o.get("open_timeout", DEFAULT_OPEN_TIMEOUT)),
                        float(o.get("read_timeout", DEFAULT_READ_TIMEOUT))),
        }
        uri = cfg.uri
        scheme = urlsplit(uri).scheme.lower()
        if len(scheme) == 1:  # ruta de Windows "C:\..." (no es un esquema de URI)
            scheme = ""
        if scheme in ("rtsp", "rtsps"):
            opts.update({"rtsp_transport": str(o.get("rtsp_transport", "tcp")), "fflags": "nobuffer",
                         "flags": "low_delay", "max_delay": "500000"})
            pwd = cfg.password.get_secret_value() if cfg.password else None
            target = _with_credentials(uri, cfg.username, pwd)
        elif scheme == "usb":
            target, fmt = usb_input(uri.split(":", 1)[1])
            kwargs["format"] = fmt
            if cfg.width and cfg.height:
                opts["video_size"] = f"{cfg.width}x{cfg.height}"
            if cfg.fps:
                opts["framerate"] = str(int(cfg.fps))
        elif scheme == "file" or scheme == "":
            target = uri[7:] if uri.startswith("file://") else uri
            if len(target) > 2 and target[0] == "/" and target[2] == ":":  # file:///C:/...
                target = target[1:]
            self._is_file = True
        else:
            raise VideoSourceError(f"esquema no soportado por pyav: {scheme!r}", retryable=False)
        kwargs["options"] = opts
        return target, kwargs

    def connect(self) -> None:
        with self._lock:
            self._close()
            self._status = SourceStatus.CONNECTING
            try:
                target, kwargs = self._open_args()
            except VideoSourceError:
                self._status = SourceStatus.ERROR
                raise
            try:
                self._container = av.open(target, mode="r", **kwargs)
                stream = self._container.streams.video[0]
                stream.thread_type = "AUTO"
            except (av.error.FFmpegError, OSError, IndexError) as exc:
                self._status = SourceStatus.ERROR
                self._close()
                retryable = not isinstance(exc, (av.error.FileNotFoundError, IndexError))
                raise VideoSourceError(f"no se pudo abrir la fuente: {type(exc).__name__}: {exc}",
                                       retryable=retryable) from exc
            rate = stream.average_rate or stream.guessed_rate
            self._meta = SourceMetadata(
                codec=stream.codec_context.name, width=stream.codec_context.width,
                height=stream.codec_context.height, nominal_fps=float(rate) if rate else None,
                extra={"container": self._container.format.name})
            self._frames = self._container.decode(stream)
            self._t0_pts = None
            self._status = SourceStatus.CONNECTED

    def disconnect(self) -> None:
        with self._lock:
            self._close()
            self._status = SourceStatus.DISCONNECTED

    def _close(self) -> None:
        if self._container is not None:
            with contextlib.suppress(Exception):
                self._container.close()
        self._container = None
        self._frames = None

    # ------------------------------------------------------------------ lectura
    def read_frame(self, timeout: float) -> Frame | None:
        """Bloquea hasta el siguiente fotograma. El plazo efectivo lo marca ``read_timeout`` de la
        conexión (FFmpeg); un atasco se notifica como ``VideoSourceError`` para que el supervisor
        reconecte. En archivos con ``loop`` se vuelve al inicio al terminar."""
        if self._frames is None:
            raise VideoSourceError("fuente no conectada")
        try:
            frame = next(self._frames)
        except StopIteration:
            if self._is_file and self.config.options.get("loop"):
                self.connect()
                return self.read_frame(timeout)
            self._status = SourceStatus.DISCONNECTED
            raise VideoSourceError("fin del stream", retryable=not self._is_file) from None
        except (av.error.FFmpegError, OSError) as exc:
            self._status = SourceStatus.ERROR
            raise VideoSourceError(f"error de lectura: {type(exc).__name__}: {exc}") from exc
        if self._is_file and self.config.options.get("realtime") and frame.time is not None:
            self._pace(frame.time)
        if self.config.width and self.config.height and urlsplit(self.config.uri).scheme != "usb":
            frame = frame.reformat(width=self.config.width, height=self.config.height)
        self._frame_id += 1
        return Frame(data=frame.to_ndarray(format="rgb24"), frame_id=self._frame_id,
                     captured_at=datetime.now(UTC), source_pts=frame.time)

    def _pace(self, pts: float) -> None:
        """Reproduce archivos a velocidad real (simula una cámara en vivo)."""
        now = time.monotonic()
        if self._t0_pts is None or pts < self._t0_pts:
            self._t0_pts, self._t0_wall = pts, now
            return
        delay = (pts - self._t0_pts) - (now - self._t0_wall)
        if delay > 0:
            time.sleep(min(delay, 1.0))

    def get_metadata(self) -> SourceMetadata:
        return self._meta

    def get_status(self) -> SourceStatus:
        return self._status
