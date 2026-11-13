"""Reportes periódicos (diario, semanal, mensual) de incidentes y cumplimiento.

Todas las cifras salen de datos persistidos (incidentes y estadísticas por minuto); nada se estima.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from enum import StrEnum


class ReportPeriod(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


PERIOD_LABEL = {ReportPeriod.DAILY: "Diario", ReportPeriod.WEEKLY: "Semanal", ReportPeriod.MONTHLY: "Mensual"}


def period_range(period: ReportPeriod, day: date, tz_offset_minutes: int) -> tuple[datetime, datetime]:
    """[inicio, fin) en UTC del periodo que contiene ``day`` en la zona del usuario.

    Semanal: de lunes a domingo (ISO). Mensual: mes natural.
    """
    if period is ReportPeriod.DAILY:
        first, last = day, day + timedelta(days=1)
    elif period is ReportPeriod.WEEKLY:
        first = day - timedelta(days=day.weekday())
        last = first + timedelta(days=7)
    else:
        first = day.replace(day=1)
        last = (first.replace(year=first.year + 1, month=1) if first.month == 12
                else first.replace(month=first.month + 1))
    tz = timezone(timedelta(minutes=tz_offset_minutes))
    start = datetime(first.year, first.month, first.day, tzinfo=tz).astimezone(UTC)
    end = datetime(last.year, last.month, last.day, tzinfo=tz).astimezone(UTC)
    return start, end


def compliance_pct(compliant: int, possible: int, confirmed: int) -> float | None:
    """Conformes / evaluables. NO_VERIFICABLE y EN_REVISION no cuentan (ni a favor ni en contra)."""
    total = compliant + possible + confirmed
    return round(100.0 * compliant / total, 1) if total else None


@dataclass(frozen=True, slots=True)
class CameraSummary:
    camera_id: str | None
    camera_name: str
    incidents: int
    confirmed_by_review: int
    discarded: int
    compliant: int
    possible: int
    confirmed: int
    unverifiable: int
    person_frames: int
    max_persons: int

    @property
    def compliance_pct(self) -> float | None:
        return compliance_pct(self.compliant, self.possible, self.confirmed)


@dataclass(frozen=True, slots=True)
class DailyRow:
    day: date
    incidents: int
    compliant: int
    possible: int
    confirmed: int
    unverifiable: int

    @property
    def compliance_pct(self) -> float | None:
        return compliance_pct(self.compliant, self.possible, self.confirmed)


@dataclass(frozen=True, slots=True)
class IncidentLine:
    id: str
    confirmed_at: datetime
    camera_name: str
    violation_type: str
    status: str
    confidence: float
    ended_at: datetime | None
    end_reason: str | None


@dataclass(slots=True)
class ReportData:
    title: str
    period: str
    start: datetime
    end: datetime
    tz_offset_minutes: int
    generated_at: datetime
    generated_by: str
    cameras_filter: list[str]  # nombres; vacío = todas
    totals: dict[str, int] = field(default_factory=dict)  # incidents, por estado de revisión...
    by_type: dict[str, int] = field(default_factory=dict)
    by_status: dict[str, int] = field(default_factory=dict)
    cameras: list[CameraSummary] = field(default_factory=list)
    days: list[DailyRow] = field(default_factory=list)
    incidents: list[IncidentLine] = field(default_factory=list)
    incidents_truncated: bool = False
    model_ids: list[str] = field(default_factory=list)

    @property
    def compliance_pct(self) -> float | None:
        c = sum(x.compliant for x in self.cameras)
        p = sum(x.possible for x in self.cameras)
        k = sum(x.confirmed for x in self.cameras)
        return compliance_pct(c, p, k)

    @property
    def unverifiable_share_pct(self) -> float | None:
        """Proporción de observaciones no verificables: indica cuánto del periodo no se pudo evaluar."""
        tot = sum(x.compliant + x.possible + x.confirmed + x.unverifiable for x in self.cameras)
        return round(100.0 * sum(x.unverifiable for x in self.cameras) / tot, 1) if tot else None

    def local(self, dt: datetime) -> datetime:
        return dt.astimezone(timezone(timedelta(minutes=self.tz_offset_minutes)))
