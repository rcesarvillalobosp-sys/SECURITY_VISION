import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Button, Empty, ErrorBox, Input, PageHeader, Select } from "../../components/ui";
import { api, type AuditEntry, type Page } from "../../lib/api";
import { fmtDateTime } from "../../lib/format";

const AREAS: Array<[string, string]> = [
  ["", "Todas las acciones"], ["auth.", "Sesiones"], ["user.", "Usuarios"], ["camera.", "Cámaras"], ["rules.", "Reglas y zonas"],
  ["incident.", "Incidentes"], ["evidence.", "Evidencias"], ["models.", "Modelos"], ["alerts.", "Alertas"], ["report.", "Reportes"],
];
const LIMIT = 50;

function Diff({ e }: { e: AuditEntry }) {
  if (!e.before && !e.after) return null;
  const keys = [...new Set([...Object.keys(e.before ?? {}), ...Object.keys(e.after ?? {})])];
  const show = (v: unknown) => (v === undefined ? "—" : typeof v === "string" ? v : JSON.stringify(v));
  return (
    <div className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 text-[11px]">
      {keys.map((k) => {
        const b = e.before?.[k];
        const a = e.after?.[k];
        const changed = JSON.stringify(a) !== JSON.stringify(b);
        return (
          <div key={k} className="contents">
            <span className="text-ink-400">{k}</span>
            <span className="num break-all">{e.before && changed ? <><span className="text-alert/80 line-through">{show(b)}</span> → </> : null}
              <span className={changed ? "text-ink-100" : "text-ink-400"}>{show(a ?? b)}</span></span>
          </div>
        );
      })}
    </div>
  );
}

export function AuditLog() {
  const [area, setArea] = useState("");
  const [entity, setEntity] = useState("");
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<number | null>(null);
  const qs = new URLSearchParams({ limit: String(LIMIT), offset: String(offset) });
  if (area) qs.set("action", area);
  if (entity.trim()) qs.set("entity_id", entity.trim());
  const q = useQuery({ queryKey: ["audit", area, entity, offset], queryFn: () => api.get<Page<AuditEntry>>(`/api/v1/audit?${qs}`) });
  const total = q.data?.total ?? 0;

  return (
    <div className="mx-auto max-w-[1300px] space-y-4">
      <PageHeader kicker="Administración" title="Registro de auditoría" actions={<>
        <Select value={area} onChange={(e) => { setArea(e.target.value); setOffset(0); }} className="!w-auto" aria-label="Área">
          {AREAS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </Select>
        <Input value={entity} onChange={(e) => { setEntity(e.target.value); setOffset(0); }} placeholder="ID de entidad" className="!w-56 num" />
      </>} />
      <p className="text-xs text-ink-400">Registro de solo inserción (la base de datos impide modificarlo o borrarlo). Nunca contiene contraseñas ni secretos.</p>
      {q.error && <ErrorBox error={q.error} />}
      <div className="panel overflow-x-auto">
        <table className="w-full min-w-[800px] text-sm">
          <thead className="border-b border-ink-700 text-left"><tr className="label">
            <th className="px-4 py-2 font-medium">Fecha</th><th className="px-4 py-2 font-medium">Acción</th>
            <th className="px-4 py-2 font-medium">Usuario</th><th className="px-4 py-2 font-medium">Entidad</th><th className="px-4 py-2 font-medium">IP</th></tr></thead>
          <tbody className="divide-y divide-ink-700">
            {(q.data?.items ?? []).map((e) => (
              <tr key={e.id} className="cursor-pointer align-top hover:bg-ink-850" onClick={() => setOpen(open === e.id ? null : e.id)}>
                <td className="num px-4 py-2 text-xs whitespace-nowrap">{fmtDateTime(e.at)}</td>
                <td className="px-4 py-2"><span className="num text-xs">{e.action}</span>{open === e.id && <Diff e={e} />}</td>
                <td className="px-4 py-2 text-xs">{e.actor_email ?? <span className="text-ink-400">sistema</span>}</td>
                <td className="px-4 py-2 text-xs"><span className="text-ink-400">{e.entity_type}</span> <span className="num">{e.entity_id?.slice(0, 13)}</span></td>
                <td className="num px-4 py-2 text-xs text-ink-400">{e.ip}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {q.data && !q.data.items.length && <Empty>Sin registros.</Empty>}
      </div>
      <div className="flex items-center justify-between text-xs text-ink-400">
        <span className="num">{total ? `${offset + 1}–${Math.min(offset + LIMIT, total)} de ${total}` : ""}</span>
        <div className="flex gap-2">
          <Button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - LIMIT))}>Anterior</Button>
          <Button disabled={offset + LIMIT >= total} onClick={() => setOffset(offset + LIMIT)}>Siguiente</Button>
        </div>
      </div>
    </div>
  );
}
