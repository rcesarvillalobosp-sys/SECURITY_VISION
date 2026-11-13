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
from security_vision.modules.detection.service import DetectionService


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


def build_inference_registry() -> ProviderRegistry:
    from security_vision.core.interfaces.inference import DetectionModel, InferenceEngine
    from security_vision.plugins.detection_models.detr import DetrDetectionModel, RfDetrModel, RtDetrModel
    from security_vision.plugins.inference_engines.onnxruntime_engine import OnnxRuntimeEngine
    from security_vision.plugins.inference_engines.openvino_engine import OpenVinoEngine

    reg = ProviderRegistry()
    reg.register(InferenceEngine, OnnxRuntimeEngine.provider_name, OnnxRuntimeEngine)
    reg.register(InferenceEngine, OpenVinoEngine.provider_name, OpenVinoEngine)
    for cls in (DetrDetectionModel, RtDetrModel, RfDetrModel):
        reg.register(DetectionModel, cls.architecture, cls)
    reg.discover(InferenceEngine)
    reg.discover(DetectionModel)
    return reg


def build_detection_service(settings: Settings, model_id: str | None = None) -> DetectionService | None:
    """Carga el modelo (``model_id`` o el configurado) en el motor/dispositivo configurado. None si no hay modelo."""
    model_id = model_id or settings.detection_model
    if not model_id:
        return None
    from security_vision.core.interfaces.inference import DetectionModel, DeviceRequest, InferenceEngine
    from security_vision.infrastructure.models.store import ModelStore

    reg = build_inference_registry()
    registered = ModelStore(Path(settings.model_registry_dir)).get(model_id)
    engine = reg.create(InferenceEngine, settings.inference_engine)
    engine.load_model(registered.artifact, DeviceRequest(preference=settings.inference_devices))
    model = reg.create(DetectionModel, registered.spec.architecture, registered.spec, engine)
    model.warmup()
    return DetectionService(model)


def build_tracking(settings: Settings):
    """Fábrica de trackers (uno por cámara) y asociador EPP (compartido, sin estado)."""
    from security_vision.core.interfaces.analysis import ObjectTracker
    from security_vision.modules.tracking.association import GeometricPPEAssociator
    from security_vision.plugins.trackers.bytetrack import ByteTrackConfig, ByteTracker

    reg = ProviderRegistry()
    reg.register(ObjectTracker, ByteTracker.provider_name, ByteTracker)
    reg.discover(ObjectTracker)
    name = settings.tracker
    cfg = ByteTrackConfig(max_lost_seconds=settings.tracker_max_lost_seconds)

    def factory() -> ObjectTracker:
        if name == ByteTracker.provider_name:
            return reg.create(ObjectTracker, name, cfg)
        return reg.create(ObjectTracker, name)

    return factory, GeometricPPEAssociator()


def build_retention(settings: Settings, engine):
    """Servicio de retención con la purga del historial de conectividad en SQL."""
    from sqlalchemy import text

    from security_vision.infrastructure.database.session import uow_factory
    from security_vision.modules.incidents.retention import RetentionDefaults, RetentionService

    async def purge_status(cutoff):
        async with engine.begin() as conn:
            res = await conn.execute(text("DELETE FROM camera_status_events WHERE at < :c"), {"c": cutoff})
            return res.rowcount

    defaults = RetentionDefaults(evidences_days=settings.retention_evidences_days,
                                 status_events_days=settings.retention_status_events_days)
    return RetentionService(uow_factory(engine), build_storage(settings), defaults, purge_status)


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
