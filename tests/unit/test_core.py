from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from security_vision.core.configuration.settings import Settings
from security_vision.core.domain.errors import AuthenticationError, ValidationError
from security_vision.core.domain.geometry import BBox, Size, point_in_polygon
from security_vision.core.domain.identity import DEFAULT_ROLES, Permission
from security_vision.core.domain.ids import uuid7
from security_vision.core.domain.vision import Detection
from security_vision.core.events.base import parse_event
from security_vision.core.events.catalog import CameraStatusChanged
from security_vision.core.interfaces.infrastructure import AccessTokenClaims
from security_vision.core.interfaces.video import SourceCapabilities, VideoSource
from security_vision.core.registry import ProviderNotFoundError, ProviderRegistry
from security_vision.infrastructure.monitoring.logging import JsonFormatter, redact
from security_vision.infrastructure.security.adapters import AesGcmCipher, Argon2PasswordHasher, JwtTokenService
from security_vision.modules.users.services import validate_password

SECRET = "x" * 40


def test_bbox_geometry_and_validation():
    a, b = BBox(0.1, 0.1, 0.5, 0.5), BBox(0.3, 0.3, 0.7, 0.7)
    assert a.iou(b) == pytest.approx(0.04 / 0.28)
    assert BBox(0.2, 0.2, 0.3, 0.3).ioa(a) == pytest.approx(1.0)
    assert a.foot_point == (0.3, 0.5)
    assert a.to_pixels(Size(1000, 500)) == (100, 50, 500, 250)
    with pytest.raises(ValueError):
        BBox(0.5, 0.5, 0.4, 0.6)
    with pytest.raises(ValueError):
        BBox(0.0, 0.0, 1.5, 0.5)
    square = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    assert point_in_polygon((0.5, 0.5), square) and not point_in_polygon((1.5, 0.5), square)


def test_detection_requires_timezone_and_valid_confidence():
    kw = dict(camera_id=uuid4(), frame_id=1, frame_size=Size(640, 480), class_name="person",
              bbox=BBox(0.1, 0.1, 0.2, 0.2), model_id="m@1", inference_ms=3.0)
    Detection(frame_ts=datetime.now(UTC), confidence=0.9, **kw)
    with pytest.raises(ValueError):
        Detection(frame_ts=datetime.now(), confidence=0.9, **kw)
    with pytest.raises(ValueError):
        Detection(frame_ts=datetime.now(UTC), confidence=1.2, **kw)


def test_uuid7_is_version_7_and_time_ordered():
    ids = [uuid7() for _ in range(50)]
    assert all(u.version == 7 and u.variant == "specified in RFC 4122" for u in ids)
    assert [u.int >> 80 for u in ids] == sorted(u.int >> 80 for u in ids)


def test_event_roundtrip():
    ev = CameraStatusChanged(camera_id=uuid4(), status="connected")
    back = parse_event(ev.envelope())
    assert back == ev and back.event_type == "camera.status_changed.v1"
    with pytest.raises(ValueError):
        parse_event({"type": "nope.v1", "payload": {}})


def test_registry_resolves_and_rejects_wrong_types():
    class FakeSource(VideoSource):
        provider_name = "fake"

        @classmethod
        def capabilities(cls):
            return SourceCapabilities(frozenset({"file"}))

        def connect(self): ...
        def disconnect(self): ...
        def read_frame(self, timeout): return None
        def get_metadata(self): ...
        def get_status(self): ...

    reg = ProviderRegistry()
    reg.register(VideoSource, "fake", FakeSource)
    assert reg.names(VideoSource) == ["fake"]
    assert reg.provider(VideoSource, "fake") is FakeSource
    with pytest.raises(ProviderNotFoundError, match="fake"):
        reg.provider(VideoSource, "gstreamer")
    with pytest.raises(TypeError):
        reg.register(VideoSource, "bad", int)  # type: ignore[arg-type]


def test_admin_role_has_every_permission_and_viewer_is_read_only():
    assert DEFAULT_ROLES["admin"][1] == frozenset(Permission)
    assert all(p.value.endswith(":read") for p in DEFAULT_ROLES["viewer"][1])


def test_argon2_hasher():
    h = Argon2PasswordHasher()
    digest = h.hash("Correcta-Horse-9")
    assert digest.startswith("$argon2id$")
    assert h.verify(digest, "Correcta-Horse-9") and not h.verify(digest, "otra")
    assert not h.verify("no-es-un-hash", "x")


def test_jwt_roundtrip_expiry_and_tamper():
    svc = JwtTokenService(SECRET, "sv")
    claims = AccessTokenClaims("u", "s", "a@b.c", ["admin"], ["users:read"],
                               datetime.now(UTC) + timedelta(minutes=5))
    token = svc.issue_access_token(claims)
    assert svc.decode_access_token(token).permissions == ["users:read"]
    with pytest.raises(AuthenticationError):
        JwtTokenService("y" * 40, "sv").decode_access_token(token)
    expired = svc.issue_access_token(AccessTokenClaims("u", "s", "", [], [], datetime.now(UTC) - timedelta(1)))
    with pytest.raises(AuthenticationError):
        svc.decode_access_token(expired)
    with pytest.raises(ValueError):
        JwtTokenService("corto", "sv")


def test_aes_gcm_cipher_authenticates_context():
    c = AesGcmCipher(AesGcmCipher.generate_key())
    blob = c.encrypt("rtsp-pass", b"camera:1")
    assert b"rtsp-pass" not in blob
    assert c.decrypt(blob, b"camera:1") == "rtsp-pass"
    with pytest.raises(Exception):  # noqa: B017 - InvalidTag de cryptography
        c.decrypt(blob, b"camera:2")


def test_log_redaction():
    assert redact("rtsp://admin:s3cr3t@10.0.0.5/stream") == "rtsp://***:***@10.0.0.5/stream"
    assert "s3cr3t" not in redact('{"password": "s3cr3t"}')
    assert "abc.def" not in redact("Authorization: Bearer abc.def")
    rec = logging.LogRecord("t", logging.INFO, "", 0, "conectando rtsp://u:p@h/x", None, None)
    assert "u:p@" not in JsonFormatter().format(rec)


def test_password_policy():
    validate_password("Sufic1ente-Larga")
    for bad in ("Corta1!", "solominusculaslarga", "SOLOMAYUSCULAS12"):
        with pytest.raises(ValidationError):
            validate_password(bad)


def test_production_rejects_example_secrets():
    with pytest.raises(PydanticValidationError):
        Settings(_env_file=None, environment="production", jwt_secret="change-me-" + "x" * 30,
                 secrets_key="k" * 43)
    Settings(_env_file=None, environment="development", jwt_secret="change-me-" + "x" * 30, secrets_key="k" * 43)


def test_production_rejects_public_demo_password():
    from security_vision.core.configuration.settings import DEMO_ADMIN_PASSWORD

    base = {"jwt_secret": "x" * 48, "secrets_key": "A" * 43 + "=", "bootstrap_admin_password": DEMO_ADMIN_PASSWORD}
    Settings(_env_file=None, environment="development", **base)  # la demo local sí funciona
    with pytest.raises(PydanticValidationError, match="demostración"):
        Settings(_env_file=None, environment="production", **base)


def test_settings_reject_unfilled_env_example_placeholders():
    """Un marcador de .env.example (``<...>``) sin completar no puede usarse como secreto."""
    import pytest
    from pydantic import ValidationError as PydanticValidationError

    from security_vision.core.configuration.settings import Settings

    base = {"database_url": "postgresql+asyncpg://u:p@h/d", "jwt_secret": "x" * 48, "secrets_key": "A" * 43 + "="}
    Settings(_env_file=None, **base)  # válido
    for field in ("jwt_secret", "mediamtx_auth_key", "bootstrap_admin_password"):
        with pytest.raises(PydanticValidationError, match="valor de ejemplo"):
            Settings(_env_file=None, **(base | {field: "<al menos 32 caracteres aleatorios>"}))
