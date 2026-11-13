"""Descubrimiento ONVIF por WS-Discovery (multicast UDP 239.255.255.250:3702), solo biblioteca estándar.

Devuelve los dispositivos que responden con su dirección de servicio (XAddrs). Obtener la URI
RTSP exacta requiere autenticarse en el servicio ONVIF del dispositivo (GetStreamUri); eso se
hace al dar de alta la cámara, no aquí.
"""

from __future__ import annotations

import re
import socket
import time
import uuid
from urllib.parse import urlsplit

from security_vision.core.interfaces.cameras import DiscoveredCamera

MCAST = ("239.255.255.250", 3702)
PROBE = """<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
 xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
 xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
 <e:Header><w:MessageID>uuid:{mid}</w:MessageID>
 <w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
 <w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action></e:Header>
 <e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body></e:Envelope>"""

_XADDRS = re.compile(r"<[^>]*XAddrs>([^<]+)</", re.IGNORECASE)
_SCOPES = re.compile(r"<[^>]*Scopes>([^<]+)</", re.IGNORECASE)


def parse_probe_match(payload: str) -> DiscoveredCamera | None:
    m = _XADDRS.search(payload)
    if not m:
        return None
    xaddrs = m.group(1).split()
    scopes = (_SCOPES.search(payload).group(1).split() if _SCOPES.search(payload) else [])
    name = next((s.rsplit("/", 1)[-1] for s in scopes if "/name/" in s), "") or urlsplit(xaddrs[0]).hostname or "?"
    hw = next((s.rsplit("/", 1)[-1] for s in scopes if "/hardware/" in s), "")
    return DiscoveredCamera(kind="onvif", name=name, address=xaddrs[0],
                            details={"hardware": hw, "all_xaddrs": " ".join(xaddrs)})


def discover_onvif(timeout: float = 2.0) -> list[DiscoveredCamera]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(0.3)
    found: dict[str, DiscoveredCamera] = {}
    try:
        sock.sendto(PROBE.format(mid=uuid.uuid4()).encode(), MCAST)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, _addr = sock.recvfrom(65535)
            except TimeoutError:
                continue
            cam = parse_probe_match(data.decode("utf-8", errors="replace"))
            if cam:
                found[cam.address] = cam
    except OSError:
        return list(found.values())
    finally:
        sock.close()
    return list(found.values())
