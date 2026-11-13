"""Canal webhook: POST JSON firmado con HMAC-SHA256.

Firma: ``X-SV-Signature: sha256=<hex(HMAC(secreto, "<X-SV-Timestamp>.<cuerpo>"))>``. El receptor debe
recalcularla y rechazar marcas de tiempo antiguas (p. ej. > 5 min) para evitar repeticiones.

Protección SSRF: por defecto se rechazan destinos que resuelvan a direcciones privadas, locales,
de enlace local, multicast o reservadas, y nunca se siguen redirecciones.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import socket
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from security_vision.core.domain.alerts import AlertChannel, AlertMessage, SendResult
from security_vision.core.domain.errors import ValidationError
from security_vision.core.interfaces.alerts import AlertSender

USER_AGENT = "SecurityVision-Alerts/1"


def validate_webhook_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValidationError("la URL del webhook debe ser http(s)://host/...")
    if parts.username or parts.password:
        raise ValidationError("no incluyas credenciales en la URL; usa el secreto de firma")
    return url.strip()


def _blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
            or ip.is_unspecified)


async def check_destination(url: str, allow_private: bool) -> str | None:
    """None si el destino es aceptable; si no, el motivo."""
    host = urlsplit(url).hostname or ""
    port = urlsplit(url).port or (443 if url.lower().startswith("https") else 80)
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        return f"no se pudo resolver {host}: {exc}"
    if allow_private:
        return None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if _blocked(ip):
            return (f"destino no permitido: {host} resuelve a {ip} (red privada o local). "
                    "Actívalo con SV_ALERT_WEBHOOK_ALLOW_PRIVATE si es intencionado")
    return None


def payload(message: AlertMessage) -> dict[str, Any]:
    return {
        "event": "incident.confirmed",
        "test": message.test,
        "delivery_id": message.delivery_id,
        "incident": {
            "id": message.incident_id,
            "camera_id": message.camera_id,
            "camera_name": message.camera_name,
            "violation_type": message.violation_type,
            "violation_label": message.violation_label,
            "confidence": round(message.confidence, 4),
            "confirmed_at": message.confirmed_at.isoformat(),
            "zone_id": message.zone_id,
            "model_id": message.model_id,
            "link": message.link,
        },
    }


def sign(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return f"sha256={mac}"


class WebhookSender(AlertSender):
    kind = "webhook"

    def __init__(self, *, timeout: float = 10.0, allow_private: bool = False,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.timeout = timeout
        self.allow_private = allow_private
        self._transport = transport

    async def send(self, channel: AlertChannel, secret: str | None, message: AlertMessage) -> SendResult:
        url = channel.config.get("url", "")
        reason = await check_destination(url, self.allow_private)
        if reason:
            return SendResult(False, reason, retryable=False)
        body = json.dumps(payload(message), ensure_ascii=False, separators=(",", ":")).encode()
        ts = str(int(time.time()))
        headers = {"Content-Type": "application/json; charset=utf-8", "User-Agent": USER_AGENT,
                   "X-SV-Event": "incident.confirmed", "X-SV-Delivery": message.delivery_id, "X-SV-Timestamp": ts}
        if secret:
            headers["X-SV-Signature"] = sign(secret, ts, body)
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False,
                                         transport=self._transport) as client:
                resp = await client.post(url, content=body, headers=headers)
        except httpx.HTTPError as exc:
            return SendResult(False, f"{type(exc).__name__}: {exc}"[:500])
        code = resp.status_code
        if 200 <= code < 300:
            return SendResult(True, response_code=code)
        detail = f"HTTP {code}: {resp.text[:300]}"
        # 408/429 y 5xx son transitorios; el resto (4xx, 3xx sin seguir) no mejora reintentando
        return SendResult(False, detail, response_code=code, retryable=code in (408, 429) or code >= 500)
