"""Consultas de los reportes: incidentes (tabla ``incidents``) y cumplimiento (``camera_stats``)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from security_vision.core.domain.reports import CameraSummary, DailyRow, IncidentLine, ReportData
from security_vision.core.interfaces.alerts import ReportSource


class SqlReportSource(ReportSource):
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def build(self, start: datetime, end: datetime, *, tz_offset_minutes: int,
                    camera_ids: Sequence[UUID] | None, max_incidents: int) -> ReportData:
        cams = list(camera_ids or [])
        p = {"s": start, "e": end, "off": tz_offset_minutes, "cams": cams, "lim": max_incidents + 1}
        f_inc = "AND i.camera_id = ANY(:cams)" if cams else ""
        f_st = "AND st.camera_id = ANY(:cams)" if cams else ""

        async with self.engine.connect() as conn:
            by_status = dict((await conn.execute(text(f"""
                SELECT status, count(*) FROM incidents i
                WHERE confirmed_at >= :s AND confirmed_at < :e {f_inc} GROUP BY status"""), p)).all())
            by_type = dict((await conn.execute(text(f"""
                SELECT violation_type, count(*) FROM incidents i
                WHERE confirmed_at >= :s AND confirmed_at < :e {f_inc} GROUP BY violation_type ORDER BY 2 DESC"""),
                p)).all())
            models = [r[0] for r in (await conn.execute(text(f"""
                SELECT DISTINCT model_id FROM incidents i
                WHERE confirmed_at >= :s AND confirmed_at < :e AND model_id IS NOT NULL {f_inc} ORDER BY 1"""),
                p)).all()]
            inc_by_cam = {(r.camera_id, r.camera_name): r for r in (await conn.execute(text(f"""
                SELECT i.camera_id, i.camera_name, count(*) AS n,
                       count(*) FILTER (WHERE status IN ('CONFIRMADO','RESUELTO')) AS confirmed_by_review,
                       count(*) FILTER (WHERE status = 'DESCARTADO') AS discarded
                FROM incidents i WHERE confirmed_at >= :s AND confirmed_at < :e {f_inc}
                GROUP BY i.camera_id, i.camera_name"""), p)).all()}
            st_by_cam = {r.camera_id: r for r in (await conn.execute(text(f"""
                SELECT st.camera_id, c.name, sum(compliant) AS compliant, sum(possible) AS possible,
                       sum(confirmed) AS confirmed, sum(unverifiable) AS unverifiable,
                       sum(person_frames) AS person_frames, max(max_persons) AS max_persons
                FROM camera_stats st JOIN cameras c ON c.id = st.camera_id
                WHERE bucket >= :s AND bucket < :e {f_st} GROUP BY st.camera_id, c.name"""), p)).all()}
            st_days = {r.d: r for r in (await conn.execute(text(f"""
                SELECT (bucket + make_interval(mins => :off))::date AS d, sum(compliant) AS compliant,
                       sum(possible) AS possible, sum(confirmed) AS confirmed, sum(unverifiable) AS unverifiable
                FROM camera_stats st WHERE bucket >= :s AND bucket < :e {f_st} GROUP BY 1"""), p)).all()}
            inc_days = dict((await conn.execute(text(f"""
                SELECT (confirmed_at + make_interval(mins => :off))::date, count(*) FROM incidents i
                WHERE confirmed_at >= :s AND confirmed_at < :e {f_inc} GROUP BY 1"""), p)).all())
            lines = (await conn.execute(text(f"""
                SELECT id, confirmed_at, camera_name, violation_type, status, confidence, ended_at, end_reason
                FROM incidents i WHERE confirmed_at >= :s AND confirmed_at < :e {f_inc}
                ORDER BY confirmed_at LIMIT :lim"""), p)).all()
            cam_names = []
            if cams:
                cam_names = [r[0] for r in (await conn.execute(
                    text("SELECT name FROM cameras WHERE id = ANY(:cams) ORDER BY name"), {"cams": cams})).all()]

        cameras: list[CameraSummary] = []
        seen: set[UUID | None] = set()
        for (cid, cname), r in sorted(inc_by_cam.items(), key=lambda kv: kv[0][1]):
            st = st_by_cam.get(cid)
            seen.add(cid)
            cameras.append(CameraSummary(
                camera_id=str(cid) if cid else None, camera_name=cname, incidents=r.n,
                confirmed_by_review=r.confirmed_by_review, discarded=r.discarded,
                compliant=int(st.compliant) if st else 0, possible=int(st.possible) if st else 0,
                confirmed=int(st.confirmed) if st else 0, unverifiable=int(st.unverifiable) if st else 0,
                person_frames=int(st.person_frames) if st else 0, max_persons=int(st.max_persons) if st else 0))
        for cid, st in sorted(st_by_cam.items(), key=lambda kv: kv[1].name):
            if cid in seen:
                continue
            cameras.append(CameraSummary(
                camera_id=str(cid), camera_name=st.name, incidents=0, confirmed_by_review=0, discarded=0,
                compliant=int(st.compliant), possible=int(st.possible), confirmed=int(st.confirmed),
                unverifiable=int(st.unverifiable), person_frames=int(st.person_frames),
                max_persons=int(st.max_persons)))

        # Todos los días del periodo, también los que no tienen datos (se ve que no hubo análisis)
        days: list[DailyRow] = []
        first: date = (start + timedelta(minutes=tz_offset_minutes)).date()
        last: date = (end + timedelta(minutes=tz_offset_minutes) - timedelta(microseconds=1)).date()
        d = first
        while d <= last:
            st = st_days.get(d)
            days.append(DailyRow(day=d, incidents=int(inc_days.get(d, 0)),
                                 compliant=int(st.compliant) if st else 0, possible=int(st.possible) if st else 0,
                                 confirmed=int(st.confirmed) if st else 0,
                                 unverifiable=int(st.unverifiable) if st else 0))
            d += timedelta(days=1)

        total = sum(by_status.values())
        return ReportData(
            title="", period="", start=start, end=end, tz_offset_minutes=tz_offset_minutes,
            generated_at=datetime.now(UTC), generated_by="", cameras_filter=cam_names,
            totals={"incidents": total, "pending": by_status.get("PENDIENTE", 0) + by_status.get("EN_REVISION", 0),
                    "confirmed_by_review": by_status.get("CONFIRMADO", 0) + by_status.get("RESUELTO", 0),
                    "discarded": by_status.get("DESCARTADO", 0)},
            by_type={k: int(v) for k, v in by_type.items()}, by_status={k: int(v) for k, v in by_status.items()},
            cameras=cameras, days=days,
            incidents=[IncidentLine(id=str(r.id), confirmed_at=r.confirmed_at, camera_name=r.camera_name,
                                    violation_type=r.violation_type, status=r.status, confidence=r.confidence,
                                    ended_at=r.ended_at, end_reason=r.end_reason) for r in lines[:max_incidents]],
            incidents_truncated=len(lines) > max_incidents, model_ids=models)
