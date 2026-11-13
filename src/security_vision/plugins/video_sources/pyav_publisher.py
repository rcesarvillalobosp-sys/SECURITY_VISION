"""Publicador RTSP con PyAV (cámara local -> MediaMTX).

Codificadores por orden de preferencia: hardware NVIDIA/Intel, Media Foundation (Windows) y VP8
(libvpx, BSD). **Nunca** libx264/libx265 (GPL), aunque las ruedas de PyAV los incluyan: así el
producto no depende de código GPL y funciona igual con una compilación LGPL de FFmpeg.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Sequence
from fractions import Fraction
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import av

from security_vision.core.interfaces.video import Frame, VideoPublisher

log = logging.getLogger(__name__)
DEFAULT_ENCODERS = ("h264_nvenc", "h264_qsv", "h264_mf", "libvpx")
FORBIDDEN_ENCODERS = {"libx264", "libx264rgb", "libx265"}


def available_encoders(preference: Sequence[str] = DEFAULT_ENCODERS) -> list[str]:
    out = []
    for name in preference:
        if name in FORBIDDEN_ENCODERS:
            continue
        try:
            av.codec.Codec(name, "w")
            out.append(name)
        except Exception:
            continue
    return out


class PyAVRtspPublisher(VideoPublisher):
    def __init__(self, url: str, fps: float, username: str | None = None, password: str | None = None,
                 encoders: Sequence[str] = DEFAULT_ENCODERS, bitrate: int = 1_500_000) -> None:
        if username:
            p = urlsplit(url)
            host = f"{p.hostname}:{p.port}" if p.port else (p.hostname or "")
            cred = quote(username, safe="") + (":" + quote(password or "", safe=""))
            url = urlunsplit((p.scheme, f"{cred}@{host}", p.path, p.query, p.fragment))
        self._url = url
        self._fps = max(1, round(fps))
        self._candidates = available_encoders(encoders)
        self._bitrate = bitrate
        self._container: Any = None
        self._stream: Any = None
        self._pts = 0
        self.encoder: str | None = None

    def _open(self, width: int, height: int) -> None:
        last_exc: Exception | None = None
        for enc in self._candidates:
            try:
                container = av.open(self._url, mode="w", format="rtsp", options={"rtsp_transport": "tcp"})
                stream = container.add_stream(enc, rate=self._fps)
                stream.width, stream.height, stream.pix_fmt = width - width % 2, height - height % 2, "yuv420p"
                stream.bit_rate = self._bitrate
                stream.time_base = Fraction(1, self._fps)
                stream.codec_context.gop_size = self._fps * 2
                if enc.startswith("h264"):
                    stream.codec_context.options = {"bf": "0"}  # sin B-frames: WebRTC los rechaza
                self._container, self._stream, self.encoder = container, stream, enc
                return
            except Exception as exc:  # probar el siguiente codificador
                last_exc = exc
                log.info("codificador %s no disponible para publicar: %s", enc, exc)
        raise RuntimeError(f"ningún codificador permitido funcionó ({self._candidates}): {last_exc}")

    def publish(self, frame: Frame) -> None:
        if self._container is None:
            self._open(frame.width, frame.height)
        vf = av.VideoFrame.from_ndarray(frame.data, format="rgb24")
        vf = vf.reformat(width=self._stream.width, height=self._stream.height, format="yuv420p")
        vf.pts = self._pts
        self._pts += 1
        for pkt in self._stream.encode(vf):
            self._container.mux(pkt)

    def close(self) -> None:
        if self._container is not None:
            try:
                for pkt in self._stream.encode():
                    self._container.mux(pkt)
            except Exception:
                pass
            with contextlib.suppress(Exception):
                self._container.close()
        self._container = self._stream = None
        self._pts = 0
