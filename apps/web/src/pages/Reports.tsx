import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { AXIS, CHART_BASE, EChart } from "../components/EChart";
import { Button, Empty, ErrorBox, Field, Input, Kpi, PageHeader, Panel, ReviewPill, Select } from "../components/ui";
import { api, download, type Camera, type Report } from "../lib/api";
import { fmtDateTime, MISSING_LABEL, pct, STATUS_COLOR } from "../lib/format";

const TZ = -new Date().getTimezoneOffset();
const PERIODS = { daily: "Diario", weekly: "Semanal (lunes a domingo)", monthly: "Mensual" } as const;
type Period = keyof typeof PERIODS;

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function Reports() {
  const [period, setPeriod] = useState<Period>("weekly");
  const [day, setDay] = useState(today());
  const [camera, setCamera] = useState("");
  const cams = useQuery({ queryKey: ["cameras"], queryFn: () => api.get<Camera[]>("/api/v1/cameras") });
  const qs = useMemo(() => {
    const p = new URLSearchParams({ date: day, tz_offset_minutes: String(TZ) });
    if (camera) p.append("camera_id", camera);
    return p;
  }, [day, camera]);
  const rep = useQuery({ queryKey: ["report", period, qs.toString()], queryFn: () => api.get<Report>(`/api/v1/reports/${period}?${qs}`),
    enabled: !!day });
  const dl = useMutation({
    mutationFn: (fmt: "pdf" | "xlsx") => download(`/api/v1/reports/${period}?${qs}&format=${fmt}`, `reporte.${fmt}`),
  });
  const r = rep.data;

  const chart = useMemo(() => {
    const days = r?.days ?? [];
    return {
      ...CHART_BASE,
      grid: { ...CHART_BASE.grid, top: 40 },
      legend: { top: 0, left: 0, textStyle: { color: "#93a1b2" }, itemWidth: 10, itemHeight: 10 },
      xAxis: { type: "category", data: days.map((d) => d.day.slice(5).split("-").reverse().join("/")), ...AXIS },
      yAxis: [{ type: "value", minInterval: 1, name: "incidentes", ...AXIS },
        { type: "value", min: 0, max: 100, name: "%", ...AXIS, splitLine: { show: false } }],
      series: [
        { name: "Incidentes", type: "bar", data: days.map((d) => d.incidents), barMaxWidth: 18, itemStyle: { color: "#f5a524" } },
        { name: "Cumplimiento %", type: "line", yAxisIndex: 1, data: days.map((d) => d.compliance_pct), connectNulls: false,
          symbol: "circle", symbolSize: 6, lineStyle: { color: STATUS_COLOR.CUMPLIMIENTO, width: 2 },
          itemStyle: { color: STATUS_COLOR.CUMPLIMIENTO } },
      ],
    };
  }, [r]);

  return (
    <div className="mx-auto max-w-[1400px] space-y-4">
      <PageHeader kicker="Análisis" title="Reportes" actions={<>
        <Button onClick={() => dl.mutate("pdf")} disabled={dl.isPending || !r}>Descargar PDF</Button>
        <Button onClick={() => dl.mutate("xlsx")} disabled={dl.isPending || !r}>Descargar Excel</Button>
      </>} />
      <div className="panel grid gap-3 p-4 sm:grid-cols-3">
        <Field label="Periodo"><Select value={period} onChange={(e) => setPeriod(e.target.value as Period)}>
          {Object.entries(PERIODS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Field>
        <Field label={period === "daily" ? "Día" : "Cualquier día del periodo"}>
          <Input type="date" value={day} max={today()} onChange={(e) => setDay(e.target.value)} /></Field>
        <Field label="Cámara"><Select value={camera} onChange={(e) => setCamera(e.target.value)}>
          <option value="">Todas</option>{(cams.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select></Field>
      </div>
      {(rep.error || dl.error) && <ErrorBox error={rep.error ?? dl.error} />}
      {r && (
        <>
          <p className="text-xs text-ink-400">Del {fmtDateTime(r.start)} al {fmtDateTime(r.end)} (hora local)
            {r.model_ids.length ? ` · modelos: ${r.model_ids.join(", ")}` : ""}</p>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <Kpi label="Incidentes" value={r.totals.incidents} tone={r.totals.incidents ? "warn" : "muted"} />
            <Kpi label="Confirmados en revisión" value={r.totals.confirmed_by_review} tone={r.totals.confirmed_by_review ? "alert" : "muted"} />
            <Kpi label="Descartados" value={r.totals.discarded} sub="falsos positivos" />
            <Kpi label="Pendientes de revisión" value={r.totals.pending} tone={r.totals.pending ? "alert" : "muted"} />
            <Kpi label="Cumplimiento" value={pct(r.compliance_pct)}
              tone={r.compliance_pct == null ? "muted" : r.compliance_pct >= 90 ? "ok" : r.compliance_pct >= 70 ? "warn" : "alert"} />
            <Kpi label="No verificable" value={pct(r.unverifiable_share_pct)} sub="de las observaciones" />
          </div>
          <div className="grid gap-4 xl:grid-cols-3">
            <Panel className="xl:col-span-2" title="Evolución diaria">
              {r.days.some((d) => d.incidents || d.compliance_pct != null) ? <EChart option={chart} height={250} />
                : <Empty>Sin datos en el periodo</Empty>}
            </Panel>
            <Panel title="Por tipo">
              {Object.keys(r.by_type).length ? (
                <ul className="space-y-2">{Object.entries(r.by_type).map(([k, v]) => (
                  <li key={k} className="flex items-center gap-3 text-sm"><span className="w-24">{MISSING_LABEL[k] ?? k}</span>
                    <span className="h-2 flex-1 overflow-hidden rounded bg-ink-800"><span className="block h-full bg-signal"
                      style={{ width: `${(100 * v) / Math.max(...Object.values(r.by_type))}%` }} /></span>
                    <span className="num w-8 text-right">{v}</span></li>))}</ul>
              ) : <Empty>Sin incidentes</Empty>}
            </Panel>
          </div>
          <Panel title="Por cámara">
            <div className="overflow-x-auto"><table className="w-full min-w-[720px] text-sm">
              <thead className="text-left"><tr className="label">
                <th className="py-1.5 pr-3 font-medium">Cámara</th><th className="py-1.5 pr-3 text-right font-medium">Incidentes</th>
                <th className="py-1.5 pr-3 text-right font-medium">Confirmados</th><th className="py-1.5 pr-3 text-right font-medium">Descartados</th>
                <th className="py-1.5 pr-3 text-right font-medium">Cumplimiento</th><th className="py-1.5 text-right font-medium">Máx. personas</th></tr></thead>
              <tbody className="num divide-y divide-ink-700">{r.cameras.map((c) => (
                <tr key={`${c.camera_id}-${c.camera_name}`}><td className="py-2 pr-3 font-sans">{c.camera_name}</td>
                  <td className="py-2 pr-3 text-right">{c.incidents}</td><td className="py-2 pr-3 text-right">{c.confirmed_by_review}</td>
                  <td className="py-2 pr-3 text-right">{c.discarded}</td><td className="py-2 pr-3 text-right">{pct(c.compliance_pct)}</td>
                  <td className="py-2 text-right">{c.max_persons}</td></tr>))}</tbody>
            </table>{!r.cameras.length && <Empty>Sin datos</Empty>}</div>
          </Panel>
          <Panel title={`Incidentes (${r.incidents.length}${r.incidents_truncated ? "+, listado limitado" : ""})`}>
            <div className="max-h-[420px] overflow-auto"><table className="w-full min-w-[640px] text-sm">
              <tbody className="divide-y divide-ink-700">{r.incidents.map((i) => (
                <tr key={i.id}><td className="num py-1.5 pr-3 text-xs">{fmtDateTime(i.confirmed_at)}</td>
                  <td className="py-1.5 pr-3">{MISSING_LABEL[i.violation_type] ?? i.violation_type}</td>
                  <td className="py-1.5 pr-3 text-ink-300">{i.camera_name}</td><td className="py-1.5 pr-3"><ReviewPill status={i.status} /></td>
                  <td className="py-1.5 text-right"><Link to={`/incidents/${i.id}`} className="text-xs text-signal hover:underline">Ver</Link></td></tr>))}</tbody>
            </table>{!r.incidents.length && <Empty>Sin incidentes en el periodo</Empty>}</div>
          </Panel>
          <p className="text-[11px] leading-snug text-ink-400">Cumplimiento = observaciones conformes / (conformes + posibles + confirmadas). Las no verificables
            y las que están en revisión no cuentan ni a favor ni en contra. Los incidentes son confirmaciones del motor sujetas a revisión humana.</p>
        </>
      )}
    </div>
  );
}
