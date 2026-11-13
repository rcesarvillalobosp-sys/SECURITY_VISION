"""Textos compartidos por los generadores de reportes."""

from __future__ import annotations

from datetime import datetime, timedelta

from security_vision.core.domain.compliance import violation_label
from security_vision.core.domain.reports import ReportData

STATUS_LABEL = {"PENDIENTE": "Pendiente", "EN_REVISION": "En revisión", "CONFIRMADO": "Confirmado",
                "DESCARTADO": "Descartado", "RESUELTO": "Resuelto"}
END_REASON_LABEL = {"corrected": "EPP visto de nuevo", "track_lost": "Persona fuera de vista"}

METHODOLOGY = (
    "Cumplimiento = observaciones conformes / (conformes + posibles + confirmadas), sobre fotogramas-persona "
    "analizados. Las observaciones no verificables (persona demasiado pequeña, recortada u ocluida) y las que "
    "están en revisión no cuentan ni a favor ni en contra; su proporción se informa aparte. Un incidente es una "
    "confirmación del motor de reglas (nunca de un solo fotograma) sujeta a revisión humana: los descartados en "
    "revisión son falsos positivos. Las detecciones del modelo pueden contener errores."
)


def tz_label(offset_minutes: int) -> str:
    sign = "+" if offset_minutes >= 0 else "-"
    h, m = divmod(abs(offset_minutes), 60)
    return f"UTC{sign}{h:02d}:{m:02d}"


def fmt_dt(r: ReportData, dt: datetime | None) -> str:
    return r.local(dt).strftime("%Y-%m-%d %H:%M:%S") if dt else ""


def naive_local(r: ReportData, dt: datetime | None) -> datetime | None:
    return r.local(dt).replace(tzinfo=None) if dt else None


def period_text(r: ReportData) -> str:
    last = r.local(r.end) - timedelta(seconds=1)
    first = r.local(r.start)
    if first.date() == last.date():
        return f"{first:%Y-%m-%d} ({tz_label(r.tz_offset_minutes)})"
    return f"{first:%Y-%m-%d} a {last:%Y-%m-%d} ({tz_label(r.tz_offset_minutes)})"


def pct(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f} %"


def vlabel(t: str) -> str:
    return violation_label(t)
