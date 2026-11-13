import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { Button, Check, confirmAction, Drawer, Empty, ErrorBox, Field, Input, PageHeader, Panel, Select, Tag } from "../../components/ui";
import { api, type AlertChannel, type AlertDelivery, type AlertsInfo, type Camera, type Page } from "../../lib/api";
import { fmtDateTime, MISSING_LABEL } from "../../lib/format";

interface TestResult { ok: boolean; detail: string | null; response_code: number | null }

function ChannelForm({ channel, cameras, info, onClose }:
  { channel?: AlertChannel; cameras: Camera[]; info?: AlertsInfo; onClose: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState(channel?.name ?? "");
  const [kind, setKind] = useState<"webhook" | "email">(channel?.kind ?? "webhook");
  const [url, setUrl] = useState(channel?.config.url ?? "");
  const [recipients, setRecipients] = useState((channel?.config.recipients ?? []).join(", "));
  const [secret, setSecret] = useState("");
  const [clearSecret, setClearSecret] = useState(false);
  const [types, setTypes] = useState<string[]>(channel?.violation_types ?? []);
  const [cams, setCams] = useState<string[]>(channel?.camera_ids ?? []);
  const [attach, setAttach] = useState(channel?.attach_evidence ?? true);
  const [enabled, setEnabled] = useState(channel?.enabled ?? true);

  const save = useMutation({
    mutationFn: () => {
      const config = kind === "webhook" ? { url: url.trim() }
        : { recipients: recipients.split(/[,;\s]+/).map((s) => s.trim()).filter(Boolean) };
      const body: Record<string, unknown> = { name: name.trim(), enabled, config, violation_types: types, camera_ids: cams,
        attach_evidence: attach };
      if (clearSecret) body.secret = "";
      else if (secret) body.secret = secret;
      return channel ? api.patch<AlertChannel>(`/api/v1/alert-channels/${channel.id}`, body)
        : api.post<AlertChannel>("/api/v1/alert-channels", { ...body, kind });
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["alert-channels"] }); onClose(); },
  });
  const toggle = (list: string[], v: string, on: boolean) => (on ? [...list, v] : list.filter((x) => x !== v));

  return (
    <Drawer title={channel ? `Editar canal · ${channel.name}` : "Nuevo canal de alerta"} onClose={onClose}
      footer={<>
        <Button variant="ghost" onClick={onClose}>Cancelar</Button>
        <Button variant="primary" disabled={save.isPending || !name.trim() || (kind === "webhook" ? !url.trim() : !recipients.trim())}
          onClick={() => save.mutate()}>{save.isPending ? "Guardando…" : "Guardar"}</Button>
      </>}>
      {save.error && <ErrorBox error={save.error} />}
      <div className="grid grid-cols-[1fr_9rem] gap-3">
        <Field label="Nombre"><Input value={name} maxLength={100} onChange={(e) => setName(e.target.value)} autoFocus /></Field>
        <Field label="Tipo">
          <Select value={kind} disabled={!!channel} onChange={(e) => setKind(e.target.value as "webhook" | "email")}>
            <option value="webhook">Webhook</option><option value="email">Correo</option>
          </Select>
        </Field>
      </div>
      {kind === "webhook" ? (
        <>
          <Field label="URL" hint={info?.webhook_allow_private ? "Se permiten destinos en la red local (SV_ALERT_WEBHOOK_ALLOW_PRIVATE)."
            : "Por seguridad (SSRF) se rechazan destinos de red privada o local."}>
            <Input value={url} maxLength={1000} placeholder="https://…" onChange={(e) => setUrl(e.target.value)} className="num" />
          </Field>
          <Field label="Secreto de firma HMAC-SHA256" hint={channel?.has_secret ? "Hay un secreto guardado (cifrado). Déjalo en blanco para conservarlo."
            : "Recomendado. El receptor verifica la cabecera X-SV-Signature."}>
            <Input type="password" value={secret} autoComplete="new-password" disabled={clearSecret} onChange={(e) => setSecret(e.target.value)} />
          </Field>
          {channel?.has_secret && <Check checked={clearSecret} onChange={setClearSecret} label="Quitar el secreto (dejar de firmar)" />}
        </>
      ) : (
        <>
          {!info?.email_available && <ErrorBox error="El servidor no tiene SMTP configurado (SV_SMTP_HOST y SV_SMTP_FROM): los correos fallarán." />}
          <Field label="Destinatarios" hint="Separados por comas. Máximo 20.">
            <Input value={recipients} onChange={(e) => setRecipients(e.target.value)} />
          </Field>
          <Check checked={attach} onChange={setAttach} label="Adjuntar la evidencia anotada (imagen)" />
        </>
      )}
      <div>
        <div className="mb-2 text-xs font-medium text-ink-300">Tipos de incumplimiento <span className="text-ink-400">(ninguno marcado = todos)</span></div>
        <div className="flex flex-wrap gap-x-4 gap-y-2">
          {Object.entries(MISSING_LABEL).map(([k, v]) => (
            <Check key={k} label={v} checked={types.includes(k)} onChange={(on) => setTypes(toggle(types, k, on))} />
          ))}
        </div>
      </div>
      <div>
        <div className="mb-2 text-xs font-medium text-ink-300">Cámaras <span className="text-ink-400">(ninguna marcada = todas)</span></div>
        <div className="flex max-h-40 flex-col gap-1.5 overflow-auto">
          {cameras.map((c) => <Check key={c.id} label={c.name} checked={cams.includes(c.id)} onChange={(on) => setCams(toggle(cams, c.id, on))} />)}
        </div>
      </div>
      <Check checked={enabled} onChange={setEnabled} label="Canal activo" />
      <p className="text-[11px] text-ink-400">Se avisa de cada incidente confirmado por el motor que encaje en los filtros, desde la creación del canal.
        La entrega se reintenta (30 s, 2 min, 8 min, 30 min, 2 h) y nunca se duplica.</p>
    </Drawer>
  );
}

const DELIVERY_TONE = { sent: "ok", pending: "warn", failed: "alert" } as const;
const DELIVERY_LABEL = { sent: "enviada", pending: "pendiente", failed: "fallida" };

export function AlertsAdmin() {
  const qc = useQueryClient();
  const info = useQuery({ queryKey: ["alerts-info"], queryFn: () => api.get<AlertsInfo>("/api/v1/alert-channels/info") });
  const channels = useQuery({ queryKey: ["alert-channels"], queryFn: () => api.get<AlertChannel[]>("/api/v1/alert-channels") });
  const cameras = useQuery({ queryKey: ["cameras"], queryFn: () => api.get<Camera[]>("/api/v1/cameras") });
  const [status, setStatus] = useState("");
  const deliveries = useQuery({
    queryKey: ["alert-deliveries", status],
    queryFn: () => api.get<Page<AlertDelivery>>(`/api/v1/alert-deliveries?limit=50${status ? `&status=${status}` : ""}`),
    refetchInterval: 10_000,
  });
  const [editing, setEditing] = useState<AlertChannel | "new" | null>(null);
  const [tests, setTests] = useState<Record<string, TestResult | "…">>({});
  const test = useMutation({
    mutationFn: async (c: AlertChannel) => {
      setTests((t) => ({ ...t, [c.id]: "…" }));
      return [c.id, await api.post<TestResult>(`/api/v1/alert-channels/${c.id}/test`)] as const;
    },
    onSuccess: ([id, r]) => setTests((t) => ({ ...t, [id]: r })),
    onError: (_e, c) => setTests((t) => ({ ...t, [c.id]: { ok: false, detail: String(_e), response_code: null } })),
  });
  const retry = useMutation({
    mutationFn: (d: AlertDelivery) => api.post<AlertDelivery>(`/api/v1/alert-deliveries/${d.id}/retry`),
    onSuccess: () => window.setTimeout(() => qc.invalidateQueries({ queryKey: ["alert-deliveries"] }), 1500),
  });
  const remove = useMutation({
    mutationFn: (c: AlertChannel) => api.del(`/api/v1/alert-channels/${c.id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alert-channels"] }),
  });
  const chName = (id: string) => channels.data?.find((c) => c.id === id)?.name ?? "—";
  const camName = (id: string) => cameras.data?.find((c) => c.id === id)?.name ?? id.slice(0, 8);

  return (
    <div className="mx-auto max-w-[1300px] space-y-4">
      <PageHeader kicker="Administración" title="Alertas"
        actions={<Button variant="primary" onClick={() => setEditing("new")}>Nuevo canal</Button>} />
      {(channels.error || remove.error || retry.error) && <ErrorBox error={channels.error ?? remove.error ?? retry.error} />}
      <p className="text-sm text-ink-300">Las alertas en pantalla llegan en vivo a cualquier usuario conectado. Aquí se configuran los avisos
        externos por webhook o correo.{info.data && !info.data.public_web_url && " Sin SV_PUBLIC_WEB_URL los avisos no incluyen enlace al incidente."}</p>
      <div className="grid gap-3 lg:grid-cols-2">
        {(channels.data ?? []).map((c) => {
          const t = tests[c.id];
          return (
            <Panel key={c.id} title={<span className="normal-case tracking-normal text-ink-100">{c.name}</span>}
              actions={<div className="flex gap-1.5"><Tag>{c.kind === "webhook" ? "Webhook" : "Correo"}</Tag>
                {c.enabled ? <Tag tone="ok">activo</Tag> : <Tag>pausado</Tag>}</div>}>
              <div className="space-y-2 text-sm">
                <div className="num truncate text-xs text-ink-300" title={c.config.url ?? c.config.recipients?.join(", ")}>
                  {c.kind === "webhook" ? c.config.url : c.config.recipients?.join(", ")}</div>
                <div className="flex flex-wrap gap-1 text-xs">
                  {c.violation_types.length ? c.violation_types.map((v) => <Tag key={v}>{MISSING_LABEL[v] ?? v}</Tag>) : <Tag>todos los tipos</Tag>}
                  {c.camera_ids.length ? c.camera_ids.map((v) => <Tag key={v}>{camName(v)}</Tag>) : <Tag>todas las cámaras</Tag>}
                  {c.kind === "webhook" && (c.has_secret ? <Tag tone="ok">firmado</Tag> : <Tag tone="warn">sin firma</Tag>)}
                  {c.kind === "email" && c.attach_evidence && <Tag>con evidencia</Tag>}
                </div>
                <div className="flex flex-wrap items-center gap-2 pt-1">
                  <Button className="!py-1 text-xs" onClick={() => test.mutate(c)} disabled={t === "…"}>{t === "…" ? "Enviando…" : "Enviar prueba"}</Button>
                  <Button variant="ghost" className="!py-1 text-xs" onClick={() => setEditing(c)}>Editar</Button>
                  <Button variant="ghost" className="!py-1 text-xs !text-alert"
                    onClick={() => confirmAction(`¿Eliminar el canal «${c.name}» y su historial de entregas?`) && remove.mutate(c)}>Eliminar</Button>
                </div>
                {t && t !== "…" && (t.ok
                  ? <p className="text-xs text-ok">Prueba entregada{t.response_code ? ` (código ${t.response_code})` : ""}.</p>
                  : <p className="text-xs break-words text-alert">Falló: {t.detail}</p>)}
              </div>
            </Panel>
          );
        })}
      </div>
      {channels.data && !channels.data.length && <div className="panel"><Empty>Sin canales externos configurados.</Empty></div>}

      <Panel title="Entregas recientes" actions={
        <Select value={status} onChange={(e) => setStatus(e.target.value)} className="!w-auto !py-1 text-xs" aria-label="Estado de entrega">
          <option value="">Todas</option><option value="sent">Enviadas</option><option value="pending">Pendientes</option><option value="failed">Fallidas</option>
        </Select>}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="text-left"><tr className="label">
              <th className="py-1.5 pr-3 font-medium">Creada</th><th className="py-1.5 pr-3 font-medium">Canal</th>
              <th className="py-1.5 pr-3 font-medium">Incidente</th><th className="py-1.5 pr-3 font-medium">Estado</th>
              <th className="py-1.5 pr-3 font-medium">Intentos</th><th className="py-1.5 font-medium">Detalle</th></tr></thead>
            <tbody className="divide-y divide-ink-700">
              {(deliveries.data?.items ?? []).map((d) => (
                <tr key={d.id}>
                  <td className="num py-2 pr-3 text-xs">{fmtDateTime(d.created_at)}</td>
                  <td className="py-2 pr-3">{chName(d.channel_id)}</td>
                  <td className="py-2 pr-3"><Link className="num text-xs text-signal hover:underline" to={`/incidents/${d.incident_id}`}>{d.incident_id.slice(0, 8)}…</Link></td>
                  <td className="py-2 pr-3"><Tag tone={DELIVERY_TONE[d.status]}>{DELIVERY_LABEL[d.status]}</Tag></td>
                  <td className="num py-2 pr-3 text-xs">{d.attempts}</td>
                  <td className="py-2 text-xs text-ink-300">
                    {d.status === "sent" ? `entregada ${fmtDateTime(d.sent_at)}` : d.last_error ?? "en cola"}
                    {d.status === "pending" && d.attempts > 0 && <span className="text-ink-400"> · reintento {fmtDateTime(d.next_attempt_at)}</span>}
                    {d.status === "failed" && <button onClick={() => retry.mutate(d)} disabled={retry.isPending}
                      className="ml-2 rounded border border-ink-600 px-1.5 py-0.5 text-[11px] text-ink-100 hover:bg-ink-800">Reintentar</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {deliveries.data && !deliveries.data.items.length && <Empty>Sin entregas.</Empty>}
        </div>
      </Panel>
      {editing && <ChannelForm channel={editing === "new" ? undefined : editing} cameras={cameras.data ?? []} info={info.data} onClose={() => setEditing(null)} />}
    </div>
  );
}
