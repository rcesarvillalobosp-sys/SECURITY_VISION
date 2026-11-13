import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { Button, Empty, ErrorBox, Panel, ReviewPill } from "../components/ui";
import { api, type IncidentDetail as Detail, type Incident, type IncidentStatus, type Page } from "../lib/api";
import { useAuth } from "../lib/auth";
import { fmtDateTime, INCIDENT_STATUS_LABEL, MISSING_LABEL, PPE_LABEL } from "../lib/format";

const STATUSES: IncidentStatus[] = ["PENDIENTE", "EN_REVISION", "CONFIRMADO", "DESCARTADO", "RESUELTO"];
const TRANSITIONS: Record<IncidentStatus, IncidentStatus[]> = {
  PENDIENTE: ["EN_REVISION", "CONFIRMADO", "DESCARTADO"],
  EN_REVISION: ["CONFIRMADO", "DESCARTADO", "PENDIENTE"],
  CONFIRMADO: ["RESUELTO", "EN_REVISION"],
  DESCARTADO: ["EN_REVISION"],
  RESUELTO: ["EN_REVISION"],
};
const KIND_LABEL: Record<string, string> = { context: "Contexto", frame: "Original", annotated: "Anotada", crop: "Recorte" };

export function Incidents() {
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const type = params.get("type") ?? "";
  const offset = Number(params.get("offset") ?? 0);
  const limit = 25;
  const q = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (status) q.set("status", status);
  if (type) q.set("violation_type", type);
  const list = useQuery({ queryKey: ["incidents", status, type, offset],
    queryFn: () => api.get<Page<Incident>>(`/api/v1/incidents?${q}`), refetchInterval: 15_000 });
  const navigate = useNavigate();
  const set = (k: string, v: string) => {
    const n = new URLSearchParams(params);
    if (v) n.set(k, v); else n.delete(k);
    n.delete("offset");
    setParams(n);
  };

  return (
    <div className="mx-auto max-w-[1400px] space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><div className="label">Gestión</div><h1 className="text-lg font-semibold">Incidentes</h1></div>
        <div className="flex flex-wrap gap-2">
          <select value={status} onChange={(e) => set("status", e.target.value)}
            className="rounded border border-ink-600 bg-ink-850 px-2 py-1.5 text-sm" aria-label="Estado">
            <option value="">Todos los estados</option>
            {STATUSES.map((s) => <option key={s} value={s}>{INCIDENT_STATUS_LABEL[s]}</option>)}
          </select>
          <select value={type} onChange={(e) => set("type", e.target.value)}
            className="rounded border border-ink-600 bg-ink-850 px-2 py-1.5 text-sm" aria-label="Tipo">
            <option value="">Todos los tipos</option>
            {Object.entries(MISSING_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
      </div>
      {list.error ? <ErrorBox error={list.error} /> : (
        <div className="panel overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="border-b border-ink-700 text-left">
              <tr className="label">
                <th className="px-4 py-2 font-medium">Confirmado</th><th className="px-4 py-2 font-medium">Tipo</th>
                <th className="px-4 py-2 font-medium">Cámara</th><th className="px-4 py-2 font-medium">Persona</th>
                <th className="px-4 py-2 font-medium">Confianza</th><th className="px-4 py-2 font-medium">Situación</th>
                <th className="px-4 py-2 font-medium">Revisión</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-700/70">
              {(list.data?.items ?? []).map((i) => (
                <tr key={i.id} onClick={() => navigate(`/incidents/${i.id}`)} className="cursor-pointer hover:bg-ink-850">
                  <td className="num px-4 py-2 text-ink-300">{fmtDateTime(i.confirmed_at)}</td>
                  <td className="px-4 py-2">{MISSING_LABEL[i.violation_type] ?? i.violation_type}</td>
                  <td className="px-4 py-2 text-ink-300">{i.camera_name}</td>
                  <td className="num px-4 py-2 text-ink-300">P{i.track_id}</td>
                  <td className="num px-4 py-2">{i.confidence.toFixed(2)}</td>
                  <td className="px-4 py-2 text-xs text-ink-400">{i.ended_at ? `finalizado (${i.end_reason})` : "activo"}</td>
                  <td className="px-4 py-2"><ReviewPill status={i.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {!list.data?.items.length && <Empty>No hay incidentes con estos filtros</Empty>}
          <div className="flex items-center justify-between border-t border-ink-700 px-4 py-2 text-xs text-ink-400">
            <span className="num">{list.data ? `${offset + 1}–${Math.min(offset + limit, list.data.total)} de ${list.data.total}` : "—"}</span>
            <span className="flex gap-2">
              <Button variant="ghost" disabled={offset === 0} onClick={() => set("offset", String(Math.max(0, offset - limit)))}>Anterior</Button>
              <Button variant="ghost" disabled={!list.data || offset + limit >= list.data.total}
                onClick={() => { const n = new URLSearchParams(params); n.set("offset", String(offset + limit)); setParams(n); }}>Siguiente</Button>
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

export function IncidentDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const qc = useQueryClient();
  const detail = useQuery({ queryKey: ["incident", id], queryFn: () => api.get<Detail>(`/api/v1/incidents/${id}`),
    staleTime: 60_000 }); // las URL de evidencia caducan a los 5 min
  const [selected, setSelected] = useState(0);
  const [note, setNote] = useState("");
  const [comment, setComment] = useState("");
  const change = useMutation({
    mutationFn: (status: IncidentStatus) => api.patch(`/api/v1/incidents/${id}/status`, { status, note: note || null }),
    onSuccess: () => { setNote(""); void qc.invalidateQueries({ queryKey: ["incident", id] }); void qc.invalidateQueries({ queryKey: ["incidents"] }); },
  });
  const addComment = useMutation({
    mutationFn: () => api.post(`/api/v1/incidents/${id}/comments`, { body: comment }),
    onSuccess: () => { setComment(""); void qc.invalidateQueries({ queryKey: ["incident", id] }); },
  });
  if (detail.error) return <ErrorBox error={detail.error} />;
  const d = detail.data;
  if (!d) return <Empty>Cargando…</Empty>;
  const ev = d.evidences.filter((e) => !e.purged);
  const current = ev[Math.min(selected, ev.length - 1)];
  const canReview = can("incidents:review");

  return (
    <div className="mx-auto max-w-[1500px] space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Link to="/incidents" className="text-xs text-signal hover:underline">← Incidentes</Link>
        <h1 className="text-lg font-semibold">{MISSING_LABEL[d.violation_type] ?? d.violation_type} · P{d.track_id}</h1>
        <ReviewPill status={d.status} />
        <span className="text-sm text-ink-400">{d.camera_name}</span>
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
        <Panel title="Evidencia">
          {current ? (
            <div className="space-y-3">
              <div className="grid place-items-center bg-ink-950">
                <img src={current.url ?? ""} alt={`Evidencia ${KIND_LABEL[current.kind] ?? current.kind}`}
                  className="max-h-[62vh] w-auto object-contain" />
              </div>
              <div className="flex gap-2 overflow-x-auto pb-1">
                {ev.map((e, i) => (
                  <button key={e.id} onClick={() => setSelected(i)}
                    className={`shrink-0 overflow-hidden rounded border ${i === selected ? "border-signal" : "border-ink-700"}`}>
                    <img src={e.url ?? ""} alt="" className="h-16 w-28 object-cover" loading="lazy" />
                    <div className="bg-ink-850 px-1.5 py-0.5 text-left text-[10px] text-ink-300">
                      {KIND_LABEL[e.kind] ?? e.kind}{typeof e.meta.seconds_before === "number" ? ` −${e.meta.seconds_before.toFixed(1)} s` : ""}
                    </div>
                  </button>
                ))}
              </div>
              <p className="num truncate text-[11px] text-ink-400" title={current.sha256}>
                {fmtDateTime(current.captured_at)} · fotograma {current.frame_id ?? "—"} · sha256 {current.sha256.slice(0, 16)}…
              </p>
            </div>
          ) : <Empty>Evidencia purgada por la política de retención</Empty>}
        </Panel>
        <div className="space-y-4">
          <Panel title="Datos">
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
              <dt className="text-ink-400">Inicio</dt><dd className="num">{fmtDateTime(d.started_at)}</dd>
              <dt className="text-ink-400">Confirmado</dt><dd className="num">{fmtDateTime(d.confirmed_at)}</dd>
              <dt className="text-ink-400">Fin</dt><dd className="num">{d.ended_at ? `${fmtDateTime(d.ended_at)} (${d.end_reason})` : "en curso"}</dd>
              <dt className="text-ink-400">Confianza</dt><dd className="num">{d.confidence.toFixed(2)} <span className="text-xs text-ink-400">(cuota de ausencia en la ventana)</span></dd>
              <dt className="text-ink-400">Observaciones</dt>
              <dd className="num text-xs">{d.details.verifiable ?? "—"} verificables · {d.details.absent_explicit ?? 0} ausencias explícitas · {d.details.present ?? 0} presencias</dd>
              <dt className="text-ink-400">Modelo</dt><dd className="num text-xs">{d.model_id ?? "—"}</dd>
            </dl>
          </Panel>
          {canReview && (
            <Panel title="Revisión">
              <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} maxLength={4000}
                placeholder="Nota (obligatoria para descartar o resolver)"
                className="w-full rounded border border-ink-600 bg-ink-850 px-2 py-1.5 text-sm outline-none focus:border-signal" />
              <div className="mt-2 flex flex-wrap gap-2">
                {TRANSITIONS[d.status].map((s) => (
                  <Button key={s} variant={s === "CONFIRMADO" ? "danger" : s === "RESUELTO" ? "primary" : "default"}
                    disabled={change.isPending} onClick={() => change.mutate(s)}>{INCIDENT_STATUS_LABEL[s]}</Button>
                ))}
              </div>
              {change.error && <div className="mt-2"><ErrorBox error={change.error} /></div>}
            </Panel>
          )}
          <Panel title="Historial y comentarios">
            <ol className="space-y-2 text-sm">
              {[...d.history.map((h) => ({ at: h.at, kind: "h" as const, h })), ...d.comments.map((c) => ({ at: c.at, kind: "c" as const, c }))]
                .sort((a, b) => a.at.localeCompare(b.at)).map((x, i) => (
                  <li key={i} className="border-l-2 border-ink-600 pl-3">
                    <div className="num text-[11px] text-ink-400">{fmtDateTime(x.at)}</div>
                    {x.kind === "h" ? (
                      <div>{x.h.action === "created" ? "Creado por el sistema" : x.h.action === "ended" ? "Situación finalizada"
                        : x.h.action === "status_changed" ? <>Estado: {INCIDENT_STATUS_LABEL[x.h.from_status ?? ""] ?? "—"} → <b>{INCIDENT_STATUS_LABEL[x.h.to_status ?? ""]}</b></>
                        : x.h.action === "commented" ? "Comentario añadido" : x.h.action}
                        {x.h.note && <div className="text-xs text-ink-300">{x.h.note}</div>}</div>
                    ) : <div className="rounded bg-ink-850 px-2 py-1">{x.c.body}</div>}
                  </li>
                ))}
            </ol>
            {canReview && (
              <form onSubmit={(e) => { e.preventDefault(); if (comment.trim()) addComment.mutate(); }} className="mt-3 flex gap-2">
                <input value={comment} onChange={(e) => setComment(e.target.value)} maxLength={4000} placeholder="Añadir comentario"
                  className="min-w-0 flex-1 rounded border border-ink-600 bg-ink-850 px-2 py-1.5 text-sm outline-none focus:border-signal" />
                <Button disabled={!comment.trim() || addComment.isPending}>Enviar</Button>
              </form>
            )}
          </Panel>
          <Panel title={`Detecciones persistidas (${d.detections.length})`}>
            <div className="max-h-48 overflow-auto text-xs">
              {d.detections.slice(0, 60).map((x, i) => (
                <div key={i} className="num flex justify-between gap-2 py-0.5 text-ink-300">
                  <span>{PPE_LABEL[x.class_name] ?? x.class_name}{x.track_id != null ? ` · P${x.track_id}` : ""}</span>
                  <span>{x.confidence.toFixed(2)} · f{x.frame_id} · {x.inference_ms.toFixed(0)} ms</span>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
