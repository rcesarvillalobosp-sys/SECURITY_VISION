import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { AXIS, CHART_BASE, EChart } from "../components/EChart";
import { Empty, ErrorBox, Kpi, Panel, ReviewPill } from "../components/ui";
import { api, type Incident, type Page, type Series, type Summary } from "../lib/api";
import { ago, MISSING_LABEL, pct, STATUS_COLOR } from "../lib/format";

const TZ = -new Date().getTimezoneOffset();
const TYPE_COLORS = ["#ff3b3b", "#ff8c1a", "#f2c94c", "#5aa9ff", "#b58cff"];

export function Dashboard() {
  const [range, setRange] = useState<"24h" | "7d" | "30d">("24h");
  const summary = useQuery({ queryKey: ["summary"], queryFn: () => api.get<Summary>(`/api/v1/dashboard/summary?tz_offset_minutes=${TZ}`),
    refetchInterval: 10_000 });
  const series = useQuery({ queryKey: ["series", range], queryFn: () => api.get<Series>(`/api/v1/dashboard/series?range=${range}`),
    refetchInterval: 60_000 });
  const recent = useQuery({ queryKey: ["incidents", "recent"],
    queryFn: () => api.get<Page<Incident>>("/api/v1/incidents?limit=8"), refetchInterval: 10_000 });

  const s = summary.data;
  const compliance = useMemo(() => {
    const pts = series.data?.compliance ?? [];
    const label = (t: string) => (series.data?.step === "hour"
      ? new Date(t).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" })
      : new Date(t).toLocaleDateString("es-ES", { day: "2-digit", month: "2-digit" }));
    return {
      ...CHART_BASE,
      grid: { ...CHART_BASE.grid, top: 44 },
      legend: { top: 0, left: 0, textStyle: { color: "#93a1b2" }, itemWidth: 10, itemHeight: 10 },
      xAxis: { type: "category", data: pts.map((p) => label(p.t)), ...AXIS },
      yAxis: [
        { type: "value", min: 0, max: 100, name: "%", ...AXIS },
        { type: "value", name: "personas", ...AXIS, splitLine: { show: false } },
      ],
      series: [
        { name: "Cumplimiento %", type: "line", smooth: true, symbol: pts.length < 3 ? "circle" : "none", symbolSize: 7,
          data: pts.map((p) => p.compliance_pct),
          lineStyle: { color: STATUS_COLOR.CUMPLIMIENTO, width: 2 }, itemStyle: { color: STATUS_COLOR.CUMPLIMIENTO },
          areaStyle: { color: "rgba(43,209,126,0.08)" }, connectNulls: true },
        { name: "Máx. personas", type: "bar", yAxisIndex: 1, data: pts.map((p) => p.max_persons), barMaxWidth: 10,
          itemStyle: { color: "#2a3644" } },
      ],
    };
  }, [series.data]);

  const byType = useMemo(() => {
    const rows = series.data?.incidents_by_day ?? [];
    const days = [...new Set(rows.map((r) => r.day))];
    const types = [...new Set(rows.map((r) => r.type))];
    return {
      ...CHART_BASE,
      legend: { top: 0, right: 0, textStyle: { color: "#93a1b2" }, itemWidth: 10, itemHeight: 10 },
      xAxis: { type: "category", data: days.map((d) => d.slice(5)), ...AXIS },
      yAxis: { type: "value", minInterval: 1, ...AXIS },
      series: types.map((t, i) => ({ name: MISSING_LABEL[t] ?? t, type: "bar", stack: "n", barMaxWidth: 18,
        itemStyle: { color: TYPE_COLORS[i % TYPE_COLORS.length] },
        data: days.map((d) => rows.find((r) => r.day === d && r.type === t)?.n ?? 0) })),
    };
  }, [series.data]);

  const distribution = useMemo(() => {
    const entries = Object.entries(s?.incidents.today_by_type ?? {});
    return {
      ...CHART_BASE, tooltip: { trigger: "item", backgroundColor: "#0f151d", borderColor: "#2a3644", textStyle: { color: "#dbe3ec" } },
      series: [{ type: "pie", radius: ["55%", "80%"], label: { color: "#93a1b2" },
        data: entries.map(([k, v], i) => ({ name: MISSING_LABEL[k] ?? k, value: v, itemStyle: { color: TYPE_COLORS[i % TYPE_COLORS.length] } })) }],
    };
  }, [s]);

  if (summary.error) return <ErrorBox error={summary.error} />;
  const compTone = s?.compliance_today_pct == null ? "muted" : s.compliance_today_pct >= 90 ? "ok" : s.compliance_today_pct >= 70 ? "warn" : "alert";

  return (
    <div className="mx-auto max-w-[1600px] space-y-4">
      <div className="flex items-end justify-between gap-4">
        <div>
          <div className="label">Visión general</div>
          <h1 className="text-lg font-semibold">Panel de seguridad</h1>
        </div>
        <span className="text-xs text-ink-400">Actualizado {s ? ago(s.generated_at) : "—"}</span>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Kpi label="Cámaras activas" value={s ? `${s.cameras.streaming}/${s.cameras.enabled}` : "—"} tone="ok" />
        <Kpi label="Desconectadas" value={s?.cameras.disconnected ?? "—"} tone={s?.cameras.disconnected ? "alert" : "muted"} />
        <Kpi label="Personas ahora" value={s?.persons_now ?? "—"} sub="en todas las cámaras" />
        <Kpi label="Incidentes hoy" value={s?.incidents.today ?? "—"} tone={s?.incidents.today ? "warn" : "muted"}
          sub={s?.incidents.discarded_today ? `${s.incidents.discarded_today} descartados` : undefined} />
        <Kpi label="Pendientes de revisión" value={s?.incidents.pending ?? "—"} tone={s?.incidents.pending ? "alert" : "muted"}
          pulse={!!s?.incidents.pending} />
        <Kpi label="Cumplimiento hoy" value={pct(s?.compliance_today_pct)} tone={compTone}
          sub="personas evaluables conformes" />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Panel className="xl:col-span-2" title="Cumplimiento y ocupación"
          actions={(
            <div className="flex gap-1">
              {(["24h", "7d", "30d"] as const).map((r) => (
                <button key={r} onClick={() => setRange(r)}
                  className={`rounded px-2 py-0.5 text-xs ${range === r ? "bg-signal text-ink-950" : "text-ink-300 hover:bg-ink-800"}`}>{r}</button>
              ))}
            </div>
          )}>
          {series.data?.compliance.length ? <EChart option={compliance} height={260} /> : <Empty>Sin datos de análisis en el periodo</Empty>}
        </Panel>
        <Panel title="Incidentes de hoy por tipo">
          {Object.keys(s?.incidents.today_by_type ?? {}).length ? <EChart option={distribution} height={260} />
            : <Empty>Sin incidentes hoy</Empty>}
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Panel className="xl:col-span-2" title={`Incidentes por día (${range})`}>
          {series.data?.incidents_by_day.length ? <EChart option={byType} height={220} /> : <Empty>Sin incidentes en el periodo</Empty>}
        </Panel>
        <Panel title="Últimos incidentes" actions={<Link to="/incidents" className="text-xs text-signal hover:underline">Ver todos</Link>}>
          <ul className="divide-y divide-ink-700">
            {(recent.data?.items ?? []).map((i) => (
              <li key={i.id}>
                <Link to={`/incidents/${i.id}`} className="flex items-center gap-3 py-2 hover:bg-ink-850">
                  <span className="text-sm">{MISSING_LABEL[i.violation_type] ?? i.violation_type}</span>
                  <span className="truncate text-xs text-ink-400">{i.camera_name}</span>
                  <span className="ml-auto flex items-center gap-2">
                    <span className="num text-xs text-ink-400">{ago(i.confirmed_at)}</span>
                    <ReviewPill status={i.status} />
                  </span>
                </Link>
              </li>
            ))}
            {!recent.data?.items.length && <Empty>Sin incidentes</Empty>}
          </ul>
        </Panel>
      </div>
    </div>
  );
}
