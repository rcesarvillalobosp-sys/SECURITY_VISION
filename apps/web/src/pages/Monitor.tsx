import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { CameraTile } from "../components/CameraTile";
import { Empty, ErrorBox, Panel } from "../components/ui";
import { api, type Camera } from "../lib/api";
import { fmtTime, MISSING_LABEL, STATUS_COLOR, STATUS_LABEL } from "../lib/format";
import { live, useLiveVersion } from "../lib/live";

const LAYOUTS = { "1": "grid-cols-1", "2x2": "grid-cols-1 lg:grid-cols-2", "3x3": "grid-cols-1 md:grid-cols-2 2xl:grid-cols-3" };

function EventFeed({ cameras }: { cameras: Camera[] }) {
  useLiveVersion();
  const names = new Map(cameras.map((c) => [c.id, c.name]));
  const events = live.events.filter((e) => e.event !== "camera.status_changed.v1" || true).slice(0, 40);
  return (
    <ul className="max-h-[70vh] space-y-1 overflow-auto pr-1 text-xs">
      {events.map((e) => {
        const d = e.data as Record<string, string>;
        const cam = names.get(String(d.camera_id)) ?? "—";
        if (e.event === "incident.confirmed.v1") {
          return (
            <li key={e.receivedAt} className="rounded border border-alert/50 bg-alert/10 px-2 py-1.5">
              <span className="num text-ink-400">{fmtTime(new Date(e.receivedAt).toISOString())}</span>{" "}
              <b className="text-alert">Incidente</b> · {MISSING_LABEL[d.violation_type] ?? d.violation_type} · {cam}
              {d.incident_id && <> · <Link className="text-signal hover:underline" to={`/incidents/${d.incident_id}`}>abrir</Link></>}
            </li>
          );
        }
        if (e.event === "person.compliance_changed.v1") {
          return (
            <li key={e.receivedAt} className="px-2 py-1">
              <span className="num text-ink-400">{fmtTime(new Date(e.receivedAt).toISOString())}</span>{" "}
              {cam} · P{d.track_id} <span style={{ color: STATUS_COLOR[d.current] }}>{STATUS_LABEL[d.current] ?? d.current}</span>
            </li>
          );
        }
        if (e.event === "camera.status_changed.v1") {
          return (
            <li key={e.receivedAt} className="px-2 py-1 text-ink-300">
              <span className="num text-ink-400">{fmtTime(new Date(e.receivedAt).toISOString())}</span> {cam}: {d.status}
            </li>
          );
        }
        return null;
      })}
      {!events.length && <Empty>Sin eventos todavía</Empty>}
    </ul>
  );
}

export function Monitor() {
  const cams = useQuery({ queryKey: ["cameras"], queryFn: () => api.get<Camera[]>("/api/v1/cameras"), refetchInterval: 10_000 });
  const [layout, setLayout] = useState<keyof typeof LAYOUTS>("2x2");
  const [focus, setFocus] = useState<string | null>(null);
  if (cams.error) return <ErrorBox error={cams.error} />;
  const all = (cams.data ?? []).filter((c) => c.enabled);
  const shown = focus ? all.filter((c) => c.id === focus) : all;

  return (
    <div className="mx-auto grid max-w-[1800px] gap-4 xl:grid-cols-[1fr_320px]">
      <div className="min-w-0 space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="label">Centro de monitoreo</div>
            <h1 className="text-lg font-semibold">{all.length} {all.length === 1 ? "cámara habilitada" : "cámaras habilitadas"}</h1>
          </div>
          <div className="flex items-center gap-1">
            {focus && <button onClick={() => setFocus(null)} className="mr-2 rounded px-2 py-1 text-xs text-signal hover:bg-ink-800">← Todas</button>}
            {(Object.keys(LAYOUTS) as (keyof typeof LAYOUTS)[]).map((l) => (
              <button key={l} onClick={() => { setLayout(l); setFocus(null); }}
                className={`num rounded px-2 py-1 text-xs ${layout === l && !focus ? "bg-signal text-ink-950" : "text-ink-300 hover:bg-ink-800"}`}>{l}</button>
            ))}
          </div>
        </div>
        {shown.length ? (
          <div className={`grid gap-3 ${focus ? "grid-cols-1" : LAYOUTS[layout]}`}>
            {shown.map((c) => <CameraTile key={c.id} camera={c} focused={focus === c.id} onFocus={() => setFocus(c.id)} />)}
          </div>
        ) : <Panel><Empty>No hay cámaras habilitadas. Se dan de alta en Administración › Cámaras y zonas.</Empty></Panel>}
        <div className="flex flex-wrap gap-3 text-[11px] text-ink-400">
          {Object.entries(STATUS_LABEL).map(([k, v]) => (
            <span key={k} className="flex items-center gap-1.5"><span className="size-2 rounded-sm" style={{ background: STATUS_COLOR[k] }} />{v}</span>
          ))}
          <span>· EPP: verde presente, rojo ausencia detectada, blanco sin persona, discontinuo = ambiguo</span>
        </div>
      </div>
      <Panel title="Eventos en vivo" className="h-fit xl:sticky xl:top-0"><EventFeed cameras={all} /></Panel>
    </div>
  );
}
