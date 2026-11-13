"""Canal email por SMTP propio (stdlib ``smtplib``), con STARTTLS o TLS implícito.

El mensaje lleva texto plano y HTML mínimo, y opcionalmente la evidencia anotada (JPEG) adjunta.
"""

from __future__ import annotations

import asyncio
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from html import escape

from security_vision.core.domain.alerts import AlertChannel, AlertMessage, SendResult
from security_vision.core.domain.errors import ValidationError
from security_vision.core.interfaces.alerts import AlertSender

EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")
MAX_RECIPIENTS = 20


def validate_recipients(recipients: list[str]) -> list[str]:
    out = list(dict.fromkeys(r.strip().lower() for r in recipients if r.strip()))
    if not out:
        raise ValidationError("indica al menos un destinatario")
    if len(out) > MAX_RECIPIENTS:
        raise ValidationError(f"máximo {MAX_RECIPIENTS} destinatarios por canal")
    bad = [r for r in out if not EMAIL_RE.match(r)]
    if bad:
        raise ValidationError(f"direcciones inválidas: {', '.join(bad)}")
    return out


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    security: str  # starttls | ssl | none
    user: str | None
    password: str | None
    sender: str
    timeout: float = 15.0


def build_email(cfg: SmtpConfig, recipients: list[str], m: AlertMessage) -> EmailMessage:
    prefix = "[PRUEBA] " if m.test else ""
    when = m.confirmed_at.astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    msg = EmailMessage()
    msg["Subject"] = f"{prefix}Incidente EPP: {m.violation_label} — {m.camera_name}"
    msg["From"] = cfg.sender
    msg["To"] = ", ".join(recipients)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=cfg.sender.split("@")[-1].strip(">"))
    msg["X-SV-Delivery"] = m.delivery_id
    lines = [
        f"{prefix}Incidente confirmado por el motor de reglas (pendiente de revisión humana).",
        "",
        f"Tipo:       {m.violation_label} ({m.violation_type})",
        f"Cámara:     {m.camera_name}",
        f"Confirmado: {when}",
        f"Confianza:  {m.confidence:.2f}",
        f"Modelo:     {m.model_id or '-'}",
        f"Incidente:  {m.incident_id}",
    ]
    if m.link:
        lines += ["", f"Ver y revisar: {m.link}"]
    lines += ["", "Este aviso es automático. La detección puede contener errores: revise la evidencia antes de actuar."]
    msg.set_content("\n".join(lines))
    rows = "".join(f"<tr><td style='color:#666;padding:2px 12px 2px 0'>{escape(k)}</td><td>{escape(v)}</td></tr>"
                   for k, v in (("Tipo", m.violation_label), ("Cámara", m.camera_name), ("Confirmado", when),
                                ("Confianza", f"{m.confidence:.2f}"), ("Modelo", m.model_id or "-"),
                                ("Incidente", m.incident_id)))
    link = f"<p><a href='{escape(m.link, quote=True)}'>Ver y revisar el incidente</a></p>" if m.link else ""
    img = "<p><img src='cid:evidence' style='max-width:640px'></p>" if m.evidence else ""
    html = (f"<div style='font-family:sans-serif'><p><b>{escape(prefix)}Incidente confirmado</b> "
            f"(pendiente de revisión humana)</p><table>{rows}</table>{link}{img}"
            "<p style='color:#888;font-size:12px'>Aviso automático. La detección puede contener errores: "
            "revise la evidencia antes de actuar.</p></div>")
    msg.add_alternative(html, subtype="html")
    if m.evidence:
        name, data, ctype = m.evidence
        maintype, subtype = ctype.split("/", 1)
        msg.get_payload()[1].add_related(data, maintype=maintype, subtype=subtype, cid="<evidence>",
                                         filename=name)
    return msg


class EmailSender(AlertSender):
    kind = "email"

    def __init__(self, cfg: SmtpConfig | None) -> None:
        self.cfg = cfg

    def _send_sync(self, recipients: list[str], msg: EmailMessage) -> None:
        cfg = self.cfg
        assert cfg is not None
        ctx = ssl.create_default_context()
        if cfg.security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=cfg.timeout, context=ctx)
        else:
            server = smtplib.SMTP(cfg.host, cfg.port, timeout=cfg.timeout)
        with server:
            server.ehlo()
            if cfg.security == "starttls":
                server.starttls(context=ctx)
                server.ehlo()
            if cfg.user and cfg.password:
                server.login(cfg.user, cfg.password)
            server.send_message(msg, from_addr=cfg.sender, to_addrs=recipients)

    async def send(self, channel: AlertChannel, secret: str | None, message: AlertMessage) -> SendResult:
        if self.cfg is None:
            return SendResult(False, "SMTP no configurado (SV_SMTP_HOST, SV_SMTP_FROM)", retryable=False)
        recipients = list(channel.config.get("recipients", []))
        try:
            await asyncio.to_thread(self._send_sync, recipients, build_email(self.cfg, recipients, message))
        except smtplib.SMTPRecipientsRefused as exc:
            return SendResult(False, f"destinatarios rechazados: {list(exc.recipients)}", retryable=False)
        except smtplib.SMTPAuthenticationError as exc:
            return SendResult(False, f"autenticación SMTP fallida ({exc.smtp_code})", exc.smtp_code, retryable=False)
        except smtplib.SMTPResponseException as exc:
            # 5xx permanente, 4xx transitorio
            return SendResult(False, f"SMTP {exc.smtp_code}: {exc.smtp_error!r}"[:500], exc.smtp_code,
                              retryable=exc.smtp_code < 500)
        except (smtplib.SMTPException, OSError) as exc:
            return SendResult(False, f"{type(exc).__name__}: {exc}"[:500])
        return SendResult(True, response_code=250)
