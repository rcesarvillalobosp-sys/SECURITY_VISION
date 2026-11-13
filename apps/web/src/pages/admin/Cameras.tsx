import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { Button, CamDot, Check, confirmAction, Drawer, Empty, ErrorBox, Field, Input, PageHeader, Select, Tag } from "../../components/ui";
import { api, type Camera, type Probe, type Profile } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { ago, CAMERA_STATUS_LABEL, SOURCE_LABEL } from "../../lib/format";

interface Discovered { kind: string; name: string; address: string; details: Record<string, string> }

interface FormState {
  name: string; source_type: string; source_uri: string; username: string; password: string; analysis_fps: string;
  enabled: boolean; default_profile_id: string; location: string;
}

const URI_HINT: Record<string, string> = {
  rtsp: "rtsp://host:554/ruta — sin usuario ni contraseña en la URL (van en sus campos, cifrados)",
  usb: "usb:Nombre del dispositivo (usa «Buscar USB»)",
  file: "Ruta relativa a la carpeta de vídeos permitida (SV_VIDEO_FILES_DIR)",
  test: "testpattern:// — patrón sintético, solo para pruebas",
};

function toForm(c?: Camera): FormState {
  return {
    name: c?.name ?? "", source_type: c?.source_type ?? "rtsp", source_uri: c?.source_uri ?? "", username: "",
    password: "", analysis_fps: String(c?.analysis_fps ?? 2), enabled: c?.enabled ?? true,
    default_profile_id: c?.default_profile_id ?? "", location: c?.location?.descripcion ?? "",
  };
}

function CameraForm({ camera, profiles, onClose }: { camera?: Camera; profiles: Profile[]; onClose: () => void }) {
  const qc = useQueryClient();
  const [f, setF] = useState<FormState>(() => toForm(camera));
  const [clearCreds, setClearCreds] = useState(false);
  const [probe, setProbe] = useState<Probe | null>(null);
  const [found, setFound] = useState<Discovered[] | null>(null);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((s) => ({ ...s, [k]: v }));

  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = {
        name: f.name.trim(), source_type: f.source_type, source_uri: f.source_uri.trim(),
        analysis_fps: Number(f.analysis_fps), enabled: f.enabled, default_profile_id: f.default_profile_id || null,
        location: f.location.trim() ? { descripcion: f.location.trim() } : {},
      };
      if (clearCreds) Object.assign(body, { username: null, password: null });
      else if (f.username.trim()) Object.assign(body, { username: f.username.trim(), password: f.password || null });
      return camera ? api.patch<Camera>(`/api/v1/cameras/${camera.id}`, body) : api.post<Camera>("/api/v1/cameras", body);
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["cameras"] }); onClose(); },
  });
  const test = useMutation({
    mutationFn: () => api.post<Probe>(`/api/v1/cameras/${camera!.id}/test`),
    onSuccess: setProbe,
  });
  const discover = useMutation({
    mutationFn: (kind: "onvif" | "usb") => api.get<Discovered[]>(`/api/v1/cameras/discover?kind=${kind}`),
    onSuccess: setFound,
  });

  return (
    <Drawer title={camera ? `Editar ${camera.name}` : "Nueva cámara"} onClose={onClose}
      footer={<>
        <Button variant="ghost" onClick={onClose}>Cancelar</Button>
        <Button variant="primary" disabled={save.isPending || !f.name.trim() || !f.source_uri.trim()}
          onClick={() => save.mutate()}>{save.isPending ? "Guardando…" : "Guardar"}</Button>
      </>}>
      {save.error && <ErrorBox error={save.error} />}
      <Field label="Nombre"><Input value={f.name} maxLength={200} onChange={(e) => set("name", e.target.value)} autoFocus /></Field>
      <div className="grid grid-cols-[minmax(0,10rem)_1fr] gap-3">
        <Field label="Tipo de fuente">
          <Select value={f.source_type} onChange={(e) => set("source_type", e.target.value)}>
            {Object.entries(SOURCE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </Select>
        </Field>
        <Field label="Origen" hint={URI_HINT[f.source_type]}>
          <Input value={f.source_uri} maxLength={1000} onChange={(e) => set("source_uri", e.target.value)} className="num" />
        </Field>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button type="button" onClick={() => discover.mutate("onvif")} disabled={discover.isPending}>Buscar ONVIF en la red</Button>
        <Button type="button" onClick={() => discover.mutate("usb")} disabled={discover.isPending}>Buscar USB</Button>
      </div>
      {discover.error && <ErrorBox error={discover.error} />}
      {found && (
        <div className="rounded border border-ink-700 p-2 text-sm">
          {found.length === 0 ? <span className="text-ink-400">No se encontró ningún dispositivo.</span> : found.map((d) => (
            <button key={d.address} type="button" className="flex w-full items-center justify-between gap-2 rounded px-2 py-1 text-left hover:bg-ink-800"
              onClick={() => { set("source_type", d.kind === "usb" ? "usb" : "rtsp"); set("source_uri", d.kind === "usb" ? d.address : ""); if (!f.name) set("name", d.name); }}>
              <span className="truncate">{d.name}</span><span className="num truncate text-xs text-ink-400">{d.address}</span>
            </button>
          ))}
          {found.some((d) => d.kind !== "usb") && <p className="mt-1 text-[11px] text-ink-400">ONVIF da la dirección del dispositivo; la URL RTSP se obtiene de su configuración.</p>}
        </div>
      )}
      {f.source_type === "rtsp" && (
        <div className="space-y-2 rounded border border-ink-700 p-3">
          <div className="label">Credenciales (se guardan cifradas)</div>
          {camera?.has_credentials && <p className="text-xs text-ink-400">Hay credenciales guardadas. Déjalas en blanco para conservarlas.</p>}
          <div className="grid grid-cols-2 gap-3">
            <Field label="Usuario"><Input value={f.username} autoComplete="off" disabled={clearCreds} onChange={(e) => set("username", e.target.value)} /></Field>
            <Field label="Contraseña"><Input type="password" value={f.password} autoComplete="new-password" disabled={clearCreds} onChange={(e) => set("password", e.target.value)} /></Field>
          </div>
          {camera?.has_credentials && <Check checked={clearCreds} onChange={setClearCreds} label="Quitar las credenciales guardadas" />}
        </div>
      )}
      <div className="grid grid-cols-2 gap-3">
        <Field label="Análisis (fotogramas/s)" hint="2–5 suele bastar; más consume GPU">
          <Input type="number" min={0.2} max={30} step={0.5} value={f.analysis_fps} onChange={(e) => set("analysis_fps", e.target.value)} />
        </Field>
        <Field label="Perfil de seguridad por defecto" hint="Fuera de las zonas se aplica este perfil">
          <Select value={f.default_profile_id} onChange={(e) => set("default_profile_id", e.target.value)}>
            <option value="">Sin perfil (no se evalúa EPP)</option>
            {profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </Select>
        </Field>
      </div>
      <Field label="Ubicación (texto libre)"><Input value={f.location} maxLength={200} onChange={(e) => set("location", e.target.value)} /></Field>
      <Check checked={f.enabled} onChange={(v) => set("enabled", v)} label="Habilitada (el worker la captura y analiza)" />
      {camera && (
        <div className="space-y-2 border-t border-ink-700 pt-3">
          <Button type="button" onClick={() => test.mutate()} disabled={test.isPending}>
            {test.isPending ? "Probando…" : "Probar conexión"}</Button>
          {test.error && <ErrorBox error={test.error} />}
          {probe && (probe.ok
            ? <p className="num text-sm text-ok">Conecta en {probe.elapsed_ms.toFixed(0)} ms · {probe.codec} {probe.width}×{probe.height}{probe.nominal_fps ? ` · ${probe.nominal_fps.toFixed(1)} fps` : ""}</p>
            : <p className="text-sm text-alert">No conecta: {probe.error}</p>)}
          <p className="text-[11px] text-ink-400">Prueba los cambios ya guardados. Una cámara USB puede aparecer ocupada si el worker ya la tiene abierta.</p>
        </div>
      )}
    </Drawer>
  );
}

export function CamerasAdmin() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const cams = useQuery({ queryKey: ["cameras"], queryFn: () => api.get<Camera[]>("/api/v1/cameras"), refetchInterval: 10_000 });
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: () => api.get<Profile[]>("/api/v1/security-profiles") });
  const [editing, setEditing] = useState<Camera | "new" | null>(null);
  const remove = useMutation({
    mutationFn: (c: Camera) => api.del(`/api/v1/cameras/${c.id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cameras"] }),
  });
  const writable = can("cameras:write");
  const profName = (id: string | null) => profiles.data?.find((p) => p.id === id)?.name;

  return (
    <div className="mx-auto max-w-[1400px] space-y-4">
      <PageHeader kicker="Administración" title="Cámaras"
        actions={writable && <Button variant="primary" onClick={() => setEditing("new")}>Nueva cámara</Button>} />
      {(cams.error || remove.error) && <ErrorBox error={cams.error ?? remove.error} />}
      <div className="panel overflow-x-auto">
        <table className="w-full min-w-[820px] text-sm">
          <thead className="border-b border-ink-700 text-left">
            <tr className="label"><th className="px-4 py-2 font-medium">Cámara</th><th className="px-4 py-2 font-medium">Fuente</th>
              <th className="px-4 py-2 font-medium">Estado</th><th className="px-4 py-2 font-medium">Perfil</th>
              <th className="px-4 py-2 font-medium">Análisis</th><th className="px-4 py-2" /></tr>
          </thead>
          <tbody className="divide-y divide-ink-700">
            {(cams.data ?? []).map((c) => (
              <tr key={c.id} className="hover:bg-ink-850">
                <td className="px-4 py-2.5">
                  <div className="flex items-center gap-2"><CamDot status={c.enabled ? c.status : "stopped"} /><span className="font-medium">{c.name}</span>
                    {!c.enabled && <Tag>deshabilitada</Tag>}</div>
                  {c.location?.descripcion && <div className="text-xs text-ink-400">{c.location.descripcion}</div>}
                </td>
                <td className="px-4 py-2.5"><div className="text-xs text-ink-300">{SOURCE_LABEL[c.source_type] ?? c.source_type}{c.has_credentials ? " · con credenciales" : ""}</div>
                  <div className="num max-w-[22rem] truncate text-xs text-ink-400" title={c.source_uri}>{c.source_uri}</div></td>
                <td className="px-4 py-2.5"><div>{CAMERA_STATUS_LABEL[c.status ?? ""] ?? c.status ?? "—"}</div>
                  <div className="text-xs text-ink-400">{c.status_at ? ago(c.status_at) : ""}</div>
                  {c.last_error && <div className="max-w-[16rem] truncate text-xs text-alert" title={c.last_error}>{c.last_error}</div>}</td>
                <td className="px-4 py-2.5 text-xs">{profName(c.default_profile_id) ?? <span className="text-ink-400">sin perfil</span>}</td>
                <td className="num px-4 py-2.5 text-xs">{c.analysis_fps} fps</td>
                <td className="px-4 py-2.5">
                  <div className="flex justify-end gap-1">
                    <Link to={`/admin/cameras/${c.id}/zones`} className="rounded px-2 py-1 text-xs text-signal hover:bg-ink-800">Zonas</Link>
                    {writable && <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={() => setEditing(c)}>Editar</Button>}
                    {writable && <Button variant="ghost" className="!px-2 !py-1 text-xs !text-alert"
                      onClick={() => confirmAction(`¿Eliminar la cámara «${c.name}»? Sus incidentes se conservan.`) && remove.mutate(c)}>Eliminar</Button>}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {cams.data && !cams.data.length && <Empty>No hay cámaras. Crea la primera.</Empty>}
      </div>
      {editing && <CameraForm camera={editing === "new" ? undefined : editing} profiles={profiles.data ?? []} onClose={() => setEditing(null)} />}
    </div>
  );
}
