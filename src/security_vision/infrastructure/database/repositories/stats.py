"""Estadísticas: escritura aditiva por minuto y consultas agregadas para el panel."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

_UPSERT = text("""
INSERT INTO camera_stats (camera_id, bucket, analyzed_frames, person_frames, max_persons,
                          compliant, in_review, possible, confirmed, unverifiable)
VALUES (:camera_id, :bucket, :analyzed_frames, :person_frames, :max_persons,
        :compliant, :in_review, :possible, :confirmed, :unverifiable)
ON CONFLICT (camera_id, bucket) DO UPDATE SET
  analyzed_frames = camera_stats.analyzed_frames + EXCLUDED.analyzed_frames,
  person_frames   = camera_stats.person_frames + EXCLUDED.person_frames,
  max_persons     = GREATEST(camera_stats.max_persons, EXCLUDED.max_persons),
  compliant       = camera_stats.compliant + EXCLUDED.compliant,
  in_review       = camera_stats.in_review + EXCLUDED.in_review,
  possible        = camera_stats.possible + EXCLUDED.possible,
  confirmed       = camera_stats.confirmed + EXCLUDED.confirmed,
  unverifiable    = camera_stats.unverifiable + EXCLUDED.unverifiable
""")


async def upsert_minutes(engine: AsyncEngine, rows: list[dict[str, Any]]) -> int:
    """``rows``: camera_id, bucket, analyzed_frames, person_frames, max_persons y contadores por estado."""
    rows = [r | {"camera_id": UUID(str(r["camera_id"]))} for r in rows]
    if not rows:
        return 0
    async with engine.begin() as conn:
        # Cámaras borradas entre el análisis y la escritura: se ignoran (FK)
        existing = {r[0] for r in (await conn.execute(
            text("SELECT id FROM cameras WHERE id = ANY(:ids)"), {"ids": list({r["camera_id"] for r in rows})}))}
        rows = [r for r in rows if r["camera_id"] in existing]
        if rows:
            await conn.execute(_UPSERT, rows)
    return len(rows)


async def compliance_series(engine: AsyncEngine, since: datetime, step: str, camera_id: UUID | None
                            ) -> list[dict[str, Any]]:
    """Serie temporal (hora o día). Cumplimiento = conformes / evaluadas verificables."""
    assert step in ("hour", "day")
    q = f"""
    SELECT date_trunc('{step}', bucket) AS t,
           sum(person_frames) AS person_frames, max(max_persons) AS max_persons,
           sum(compliant) AS compliant, sum(in_review) AS in_review, sum(possible) AS possible,
           sum(confirmed) AS confirmed, sum(unverifiable) AS unverifiable
    FROM camera_stats WHERE bucket >= :since {"AND camera_id = :cam" if camera_id else ""}
    GROUP BY 1 ORDER BY 1"""
    params: dict[str, Any] = {"since": since}
    if camera_id:
        params["cam"] = camera_id
    async with engine.connect() as conn:
        rows = (await conn.execute(text(q), params)).mappings().all()
    out = []
    for r in rows:
        decided = r["compliant"] + r["possible"] + r["confirmed"]
        out.append({"t": r["t"].isoformat(), "person_frames": int(r["person_frames"]),
                    "max_persons": int(r["max_persons"]), "compliant": int(r["compliant"]),
                    "in_review": int(r["in_review"]), "possible": int(r["possible"]),
                    "confirmed": int(r["confirmed"]), "unverifiable": int(r["unverifiable"]),
                    "compliance_pct": round(100 * r["compliant"] / decided, 1) if decided else None})
    return out


async def incidents_by_day(engine: AsyncEngine, since: datetime) -> list[dict[str, Any]]:
    q = text("""SELECT date_trunc('day', confirmed_at) AS d, violation_type, count(*) AS n
                FROM incidents WHERE confirmed_at >= :since AND status <> 'DESCARTADO'
                GROUP BY 1, 2 ORDER BY 1""")
    async with engine.connect() as conn:
        rows = (await conn.execute(q, {"since": since})).all()
    return [{"day": r.d.date().isoformat(), "type": r.violation_type, "n": int(r.n)} for r in rows]


async def summary(engine: AsyncEngine, day_start: datetime) -> dict[str, Any]:
    async with engine.connect() as conn:
        cams = (await conn.execute(text(
            "SELECT enabled, coalesce(last_status, 'desconocido') AS s, count(*) FROM cameras GROUP BY 1, 2"))).all()
        inc = (await conn.execute(text("""
            SELECT count(*) FILTER (WHERE confirmed_at >= :d AND status <> 'DESCARTADO') AS today,
                   count(*) FILTER (WHERE status IN ('PENDIENTE', 'EN_REVISION')) AS pending,
                   count(*) FILTER (WHERE confirmed_at >= :d AND status = 'DESCARTADO') AS discarded_today
            FROM incidents"""), {"d": day_start})).one()
        by_type = (await conn.execute(text("""
            SELECT violation_type, count(*) FROM incidents
            WHERE confirmed_at >= :d AND status <> 'DESCARTADO' GROUP BY 1 ORDER BY 2 DESC"""),
            {"d": day_start})).all()
        st = (await conn.execute(text("""
            SELECT coalesce(sum(compliant),0) c, coalesce(sum(possible),0) p, coalesce(sum(confirmed),0) k,
                   coalesce(sum(person_frames),0) pf, coalesce(sum(analyzed_frames),0) af
            FROM camera_stats WHERE bucket >= :d"""), {"d": day_start})).one()
    active = sum(n for enabled, s, n in cams if enabled and s == "streaming")
    enabled_total = sum(n for enabled, _s, n in cams if enabled)
    decided = st.c + st.p + st.k
    return {
        "cameras": {"total": sum(n for *_x, n in cams), "enabled": enabled_total, "streaming": active,
                    "disconnected": enabled_total - active},
        "incidents": {"today": int(inc.today), "pending": int(inc.pending),
                      "discarded_today": int(inc.discarded_today),
                      "today_by_type": {t: int(n) for t, n in by_type}},
        "compliance_today_pct": round(100 * st.c / decided, 1) if decided else None,
        "avg_persons_per_frame_today": round(st.pf / st.af, 2) if st.af else None,
    }
