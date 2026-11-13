"""Reporte en Excel con openpyxl (licencia MIT): datos tabulares listos para filtrar, con gráficas nativas."""

from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from security_vision.core.domain.reports import ReportData
from security_vision.core.interfaces.alerts import ReportRenderer

from .common import END_REASON_LABEL, METHODOLOGY, STATUS_LABEL, naive_local, period_text, vlabel

HEAD_FONT = Font(bold=True, color="1D2733")
HEAD_FILL = PatternFill("solid", fgColor="EEF1F4")


def _safe(v: object) -> object:
    """Evita la inyección de fórmulas (CSV/Excel injection) en textos que vienen de usuarios."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def _header(ws: Worksheet, row: int, titles: list[str]) -> None:
    for i, t in enumerate(titles, 1):
        c = ws.cell(row=row, column=i, value=t)
        c.font, c.fill = HEAD_FONT, HEAD_FILL
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def _widths(ws: Worksheet, widths: list[int]) -> None:
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


class XlsxReportRenderer(ReportRenderer):
    format = "xlsx"
    content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def render(self, report: ReportData) -> bytes:
        r = report
        wb = Workbook()
        ws = wb.active
        ws.title = "Resumen"
        ws["A1"] = _safe(r.title)
        ws["A1"].font = Font(bold=True, size=14)
        meta = [("Periodo", period_text(r)),
                ("Cámaras", ", ".join(r.cameras_filter) if r.cameras_filter else "todas"),
                ("Generado", naive_local(r, r.generated_at)), ("Generado por", r.generated_by),
                ("Modelos", ", ".join(r.model_ids) or "—"), ("", ""),
                ("Incidentes", r.totals.get("incidents", 0)),
                ("Confirmados en revisión", r.totals.get("confirmed_by_review", 0)),
                ("Descartados (falsos positivos)", r.totals.get("discarded", 0)),
                ("Pendientes de revisión", r.totals.get("pending", 0)),
                ("Cumplimiento (%)", r.compliance_pct), ("No verificable (%)", r.unverifiable_share_pct)]
        for i, (k, v) in enumerate(meta, 3):
            ws.cell(row=i, column=1, value=k).font = Font(bold=bool(k))
            c = ws.cell(row=i, column=2, value=_safe(v))
            if hasattr(v, "year"):
                c.number_format = "yyyy-mm-dd hh:mm:ss"
        row = 3 + len(meta) + 1
        ws.cell(row=row, column=1, value="Incidentes por tipo").font = Font(bold=True)
        _header_row = row + 1
        for i, t in enumerate(["Tipo", "Incidentes"], 1):
            c = ws.cell(row=_header_row, column=i, value=t)
            c.font, c.fill = HEAD_FONT, HEAD_FILL
        for j, (k, v) in enumerate(r.by_type.items(), _header_row + 1):
            ws.cell(row=j, column=1, value=vlabel(k))
            ws.cell(row=j, column=2, value=v)
        row = _header_row + len(r.by_type) + 2
        ws.cell(row=row, column=1, value="Metodología").font = Font(bold=True)
        c = ws.cell(row=row + 1, column=1, value=METHODOLOGY)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=row + 1, start_column=1, end_row=row + 1, end_column=6)
        ws.row_dimensions[row + 1].height = 90
        _widths(ws, [32, 36, 12, 12, 12, 12])

        wd = wb.create_sheet("Por día")
        _header(wd, 1, ["Día", "Incidentes", "Conformes", "Posibles", "Confirmados", "No verificables",
                        "Cumplimiento (%)"])
        for i, d in enumerate(r.days, 2):
            wd.cell(row=i, column=1, value=d.day).number_format = "yyyy-mm-dd"
            for j, v in enumerate([d.incidents, d.compliant, d.possible, d.confirmed, d.unverifiable,
                                   d.compliance_pct], 2):
                wd.cell(row=i, column=j, value=v)
        _widths(wd, [12, 11, 11, 11, 12, 15, 16])
        if r.days:
            n = len(r.days) + 1
            cats = Reference(wd, min_col=1, min_row=2, max_row=n)
            bar = BarChart()
            bar.title, bar.y_axis.title, bar.height, bar.width = "Incidentes por día", "Incidentes", 7, 16
            bar.add_data(Reference(wd, min_col=2, min_row=1, max_row=n), titles_from_data=True)
            bar.set_categories(cats)
            wd.add_chart(bar, "I2")
            line = LineChart()
            line.title, line.y_axis.title, line.height, line.width = "Cumplimiento diario (%)", "%", 7, 16
            line.y_axis.scaling.min, line.y_axis.scaling.max = 0, 100
            line.add_data(Reference(wd, min_col=7, min_row=1, max_row=n), titles_from_data=True)
            line.set_categories(cats)
            wd.add_chart(line, "I18")

        wc = wb.create_sheet("Por cámara")
        _header(wc, 1, ["Cámara", "Incidentes", "Confirmados en revisión", "Descartados", "Conformes", "Posibles",
                        "Confirmados", "No verificables", "Cumplimiento (%)", "Fotogramas-persona", "Máx. personas"])
        for i, c in enumerate(r.cameras, 2):
            for j, v in enumerate([_safe(c.camera_name), c.incidents, c.confirmed_by_review, c.discarded,
                                   c.compliant, c.possible, c.confirmed, c.unverifiable, c.compliance_pct,
                                   c.person_frames, c.max_persons], 1):
                wc.cell(row=i, column=j, value=v)
        _widths(wc, [30, 11, 22, 12, 11, 10, 12, 15, 16, 18, 14])

        wi = wb.create_sheet("Incidentes")
        _header(wi, 1, ["ID", "Confirmado", "Cámara", "Tipo", "Estado", "Confianza", "Fin", "Motivo de cierre"])
        for i, x in enumerate(r.incidents, 2):
            vals = [x.id, naive_local(r, x.confirmed_at), _safe(x.camera_name), vlabel(x.violation_type),
                    STATUS_LABEL.get(x.status, x.status), round(x.confidence, 4), naive_local(r, x.ended_at),
                    END_REASON_LABEL.get(x.end_reason or "", x.end_reason or "")]
            for j, v in enumerate(vals, 1):
                cell = wi.cell(row=i, column=j, value=v)
                if j in (2, 7) and v is not None:
                    cell.number_format = "yyyy-mm-dd hh:mm:ss"
        if r.incidents:
            wi.auto_filter.ref = f"A1:H{len(r.incidents) + 1}"
        if r.incidents_truncated:
            wi.cell(row=len(r.incidents) + 3, column=1,
                    value=f"Listado limitado a {len(r.incidents)} incidentes (use un periodo o filtro más estrecho).")
        _widths(wi, [38, 20, 28, 14, 13, 10, 20, 22])

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
