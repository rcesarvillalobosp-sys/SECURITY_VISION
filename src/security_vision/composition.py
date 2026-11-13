"""Fábricas compartidas por las raíces de composición (API y worker).

Único lugar de ``security_vision`` que conoce adaptadores concretos; los módulos de negocio
siguen dependiendo solo de puertos.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path

from security_vision.core.configuration.settings import Settings
from security_vision.core.interfaces.cameras import MediaServer
from security_vision.core.interfaces.video import VideoSource
from security_vision.core.registry import ProviderRegistry
from security_vision.infrastructure.storage.local import LocalFileStorage
from security_vision.modules.cameras.service import CameraPolicy


def build_video_registry() -> ProviderRegistry:
    """Proveedores incluidos + los declarados por plugins externos (entry points)."""
    from security_vision.plugins.video_sources.pyav_source import PyAVVideoSource
    from security_vision.plugins.video_sources.test_pattern import TestPatternSource

    reg = ProviderRegistry()
    reg.register(VideoSource, PyAVVideoSource.provider_name, PyAVVideoSource)
    reg.register(VideoSource, TestPatternSource.provider_name, TestPatternSource)
    for name in reg.discover(VideoSource):
        _ = name  # plugins de terceros ya registrados
    return reg


def build_storage(settings: Settings) -> LocalFileStorage:
    key = hashlib.sha256(b"storage-signing:" + settings.secrets_key.get_secret_value().encode()).digest()
    return LocalFileStorage(Path(settings.storage_dir), signing_key=key)


def build_media(settings: Settings) -> MediaServer | None:
    if not settings.mediamtx_api_url:
        return None
    from security_vision.infrastructure.video.mediamtx import MediaMtxServer

    pwd = settings.mediamtx_api_password.get_secret_value() if settings.mediamtx_api_password else None
    return MediaMtxServer(settings.mediamtx_api_url, settings.mediamtx_rtsp_url, settings.mediamtx_webrtc_url,
                          settings.mediamtx_api_user, pwd)


def camera_policy(settings: Settings) -> CameraPolicy:
    files_root = Path(settings.video_files_dir).resolve().as_posix() if settings.video_files_dir else None
    return CameraPolicy(video_provider=settings.video_provider, allow_test_sources=settings.allow_test_sources,
                        files_root=files_root, probe_timeout=settings.camera_probe_timeout,
                        snapshot_max_age=timedelta(seconds=max(30.0, settings.worker_snapshot_seconds * 4)))
