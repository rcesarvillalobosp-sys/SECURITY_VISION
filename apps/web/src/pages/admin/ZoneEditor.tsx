import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState, type PointerEvent as RPointerEvent } from "react";
import { Link, useParams } from "react-router";
import { Button, confirmAction, ErrorBox, Field, Input, PageHeader, Panel, Select, Tag } from "../../components/ui";
import { api, ApiError, request, type Camera, type Profile, type Zone } from "../../lib/api";
import { useAuth } from "../../lib/auth";

type Pt = [number, number];
interface Draft { id: string | null; name: string; kind: "ppe" | "restricted"; profile_id: string; polygon: Pt[] }

const ZONE_COLORS = ["#f5a524", "#5aa9ff", "#b58cff", "#2bd17e", "#ff8c1a", "#e86bb0"];
const clamp = (v: number) => Math.min(1, Math.max(0, v));
const round = (v: number) => Math.round(v * 10000) / 10000;

/** Imagen de la cámara: último snapshot del worker (autenticado). */
function useSnapshot(cameraId: string) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const load = useCallback(async () => {
    try {
      const blob = await request<Blob>(`/api/v1/cameras/${cameraId}/snapshot`);
      setError(null);
      setUrl((old) => { if (old) URL.revokeObjectURL(old); return URL.createObjectURL(blob); });
    } catch (e) {
      setError(e instanceof ApiError && e.status === 404 ? "Sin imagen reciente: ¿el worker está en marcha y la cámara transmite?"
        : String(e));
    }
  }, [cameraId]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => () => { setUrl((old) => { if (old) URL.revokeObjectURL(old); return null; }); }, []);
  return { url, error, size, setSize, reload: load };
}

export function ZoneEditor() {
  const { id = "" } = useParams();
  const { can } = useAuth();
  const qc = useQueryClient();
  const writable = can("zones:write");
  const cam = useQuery({ queryKey: ["camera", id], queryFn: () => api.get<Camera>(`/api/v1/cameras/${id}`) });
  const zones = useQuery({ queryKey: ["zones", id], queryFn: () => api.get<Zone[]>(`/api/v1/cameras/${id}/zones`) });
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: () => api.get<Profile[]>("/api/v1/security-profiles") });
  const snap = useSnapshot(id);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [drawing, setDrawing] = useState(false);
  const [hover, setHover] = useState<Pt | null>(null);
  const drag = useRef<number | null>(null);
  const svg = useRef<SVGSVGElement>(null);
  // Tamaño en píxeles del lienzo: las zonas se guardan normalizadas [0,1] pero se dibujan en píxeles
  // (así los vértices son círculos y el texto no se deforma).
  const [box, setBox] = useState({ w: 1, h: 1 });
  useEffect(() => {
    const el = svg.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setBox({ w: Math.max(1, e.contentRect.width), h: Math.max(1, e.contentRect.height) }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const X = (p: Pt | number[]) => p[0] * box.w;
  const Y = (p: Pt | number[]) => p[1] * box.h;
  const pts = (poly: Array<Pt | number[]>) => poly.map((q) => `${X(q)},${Y(q)}`).join(" ");

  const toPt = (e: { clientX: number; clientY: number }): Pt => {
    const r = svg.current!.getBoundingClientRect();
    return [round(clamp((e.clientX - r.left) / r.width)), round(clamp((e.clientY - r.top) / r.height))];
  };

  const startNew = () => {
    setDraft({ id: null, name: `Zona ${(zones.data?.length ?? 0) + 1}`, kind: "ppe", profile_id: "", polygon: [] });
    setDrawing(true);
  };
  const select = (z: Zone) => {
    if (drawing) return;
    setDraft({ id: z.id, name: z.name, kind: z.kind, profile_id: z.profile_id ?? "", polygon: z.polygon.map(([x, y]) => [x, y] as Pt) });
  };
  const finish = () => { if (draft && draft.polygon.length >= 3) setDrawing(false); };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!draft) return;
      if (e.key === "Escape") { setDraft(null); setDrawing(false); }
      if (e.key === "Enter" && drawing) finish();
      if ((e.key === "Backspace" || e.key === "z") && drawing && draft.polygon.length && (e.target as HTMLElement).tagName !== "INPUT") {
        setDraft({ ...draft, polygon: draft.polygon.slice(0, -1) });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const onCanvasDown = (e: RPointerEvent<SVGSVGElement>) => {
    if (!writable || !draft || !drawing) return;
    const p = toPt(e);
    const first = draft.polygon[0];
    const r = svg.current!.getBoundingClientRect();
    if (first && draft.polygon.length >= 3 && Math.hypot((first[0] - p[0]) * r.width, (first[1] - p[1]) * r.height) < 12) {
      finish();
      return;
    }
    if (draft.polygon.length < 64) setDraft({ ...draft, polygon: [...draft.polygon, p] });
  };
  const onMove = (e: RPointerEvent<SVGSVGElement>) => {
    const p = toPt(e);
    if (drawing) setHover(p);
    if (drag.current !== null && draft) {
      const poly = draft.polygon.slice();
      poly[drag.current] = p;
      setDraft({ ...draft, polygon: poly });
    }
  };
  const onUp = () => { drag.current = null; };

  const save = useMutation({
    mutationFn: (d: Draft) => {
      const body = { name: d.name.trim(), kind: d.kind, profile_id: d.profile_id || null, polygon: d.polygon };
      return d.id ? api.patch<Zone>(`/api/v1/zones/${d.id}`, body) : api.post<Zone>(`/api/v1/cameras/${id}/zones`, body);
    },
    onSuccess: (z) => { qc.invalidateQueries({ queryKey: ["zones", id] }); select(z); },
  });
  const remove = useMutation({
    mutationFn: (zid: string) => api.del(`/api/v1/zones/${zid}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["zones", id] }); setDraft(null); },
  });

  const shown = (zones.data ?? []).filter((z) => z.id !== draft?.id);
  const aspect = snap.size ? `${snap.size.w} / ${snap.size.h}` : "16 / 9";
  const profName = (pid: string | null) => profiles.data?.find((p) => p.id === pid)?.name;
  const valid = !!draft && draft.polygon.length >= 3 && !!draft.name.trim() && !drawing;

  return (
    <div className="mx-auto max-w-[1500px] space-y-4">
      <PageHeader kicker={<Link to="/admin/cameras" className="hover:text-signal">Cámaras</Link>}
        title={`Zonas · ${cam.data?.name ?? "…"}`}
        actions={<>
          <Button onClick={snap.reload}>Actualizar imagen</Button>
          {writable && <Button variant="primary" onClick={startNew} disabled={drawing}>Nueva zona</Button>}
        </>} />
      {(cam.error || zones.error) && <ErrorBox error={cam.error ?? zones.error} />}
      <div className="grid gap-4 xl:grid-cols-[1fr_22rem]">
        <Panel title={drawing ? "Dibujando: clic para añadir vértices · clic en el primero o Intro para cerrar · Retroceso deshace · Esc cancela"
          : draft ? "Arrastra los vértices para ajustar la zona" : "Selecciona una zona o crea una nueva"}>
          <div className="relative mx-auto w-full overflow-hidden rounded border border-ink-700 bg-ink-950" style={{ aspectRatio: aspect }}>
            {snap.url ? (
              <img src={snap.url} alt={`Imagen de ${cam.data?.name ?? "la cámara"}`} className="absolute inset-0 size-full select-none"
                draggable={false} onLoad={(e) => snap.setSize({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })} />
            ) : (
              <div className="absolute inset-0 grid place-items-center p-6 text-center text-sm text-ink-400">
                {snap.error ?? "Cargando imagen…"}<br />Puedes dibujar igualmente: las coordenadas son relativas al encuadre.
              </div>
            )}
            <svg ref={svg} viewBox={`0 0 ${box.w} ${box.h}`}
              className={`absolute inset-0 size-full touch-none ${drawing ? "cursor-crosshair" : ""}`}
              onPointerDown={onCanvasDown} onPointerMove={onMove} onPointerUp={onUp} onPointerLeave={() => { onUp(); setHover(null); }}>
              {shown.map((z, i) => {
                const c = z.kind === "restricted" ? "#ff3b3b" : ZONE_COLORS[i % ZONE_COLORS.length];
                return (
                  <g key={z.id} onPointerDown={(e) => { if (!drawing) { e.stopPropagation(); select(z); } }} className="cursor-pointer">
                    <polygon points={pts(z.polygon)} fill={c} fillOpacity={0.14} stroke={c} strokeWidth={2} />
                    <text x={X(z.polygon[0])} y={Y(z.polygon[0])} dy={-6} fontSize={13} fontWeight={600} fill={c}
                      style={{ paintOrder: "stroke", stroke: "#000", strokeWidth: 3 }}>{z.name}</text>
                  </g>
                );
              })}
              {draft && draft.polygon.length > 0 && (
                <g>
                  {drawing
                    ? <polyline points={pts([...draft.polygon, ...(hover ? [hover] : [])])}
                        fill="none" stroke="#f5a524" strokeWidth={2} strokeDasharray="6 4" />
                    : <polygon points={pts(draft.polygon)} fill="#f5a524" fillOpacity={0.2} stroke="#f5a524" strokeWidth={2.5} />}
                  {!drawing && writable && draft.polygon.map((p, i) => {
                    const q = draft.polygon[(i + 1) % draft.polygon.length];
                    const mid: Pt = [round((p[0] + q[0]) / 2), round((p[1] + q[1]) / 2)];
                    return (
                      <circle key={`m${i}`} cx={X(mid)} cy={Y(mid)} r={4.5} fill="#f5a524" fillOpacity={0.5}
                        className="cursor-copy" aria-label="Insertar vértice"
                        onPointerDown={(e) => {
                          e.stopPropagation();
                          if (draft.polygon.length >= 64) return;
                          const poly = draft.polygon.slice();
                          poly.splice(i + 1, 0, mid);
                          setDraft({ ...draft, polygon: poly });
                          drag.current = i + 1;
                        }} />
                    );
                  })}
                  {draft.polygon.map((p, i) => (
                    <circle key={i} cx={X(p)} cy={Y(p)} r={i === 0 && drawing ? 8 : 6}
                      fill={i === 0 && drawing ? "#f5a524" : "#0b1016"} stroke="#f5a524" strokeWidth={2}
                      className={drawing ? "" : "cursor-move"}
                      onPointerDown={(e) => {
                        if (drawing || !writable) return;
                        e.stopPropagation();
                        drag.current = i;
                      }}
                      onDoubleClick={(e) => {
                        e.stopPropagation();
                        if (!drawing && writable && draft.polygon.length > 3) {
                          setDraft({ ...draft, polygon: draft.polygon.filter((_, j) => j !== i) });
                        }
                      }} />
                  ))}
                </g>
              )}
            </svg>
          </div>
          <p className="mt-2 text-[11px] text-ink-400">
            Una persona está dentro de una zona cuando su <b>punto de apoyo</b> (el centro del borde inferior de su caja) cae dentro del polígono.
            En el solape de varias zonas se exige la unión de sus EPP. Fuera de las zonas se aplica el perfil por defecto de la cámara.
            Doble clic en un vértice lo elimina; los puntos intermedios insertan uno nuevo.
          </p>
        </Panel>

        <div className="space-y-4">
          {draft && (
            <Panel title={draft.id ? "Editar zona" : "Nueva zona"}>
              <div className="space-y-3">
                {save.error && <ErrorBox error={save.error} />}
                <Field label="Nombre"><Input value={draft.name} maxLength={200} onChange={(e) => setDraft({ ...draft, name: e.target.value })} disabled={!writable} /></Field>
                <Field label="Perfil exigido en la zona" hint="Qué EPP se exige a las personas cuyo punto de apoyo cae en esta zona.">
                  <Select value={draft.profile_id} onChange={(e) => setDraft({ ...draft, profile_id: e.target.value })} disabled={!writable}>
                    <option value="">El perfil por defecto de la cámara</option>
                    {(profiles.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                  </Select>
                </Field>
                <div className="num text-xs text-ink-400">{draft.polygon.length} vértices{draft.polygon.length < 3 ? " (mínimo 3)" : ""}</div>
                {writable && (
                  <div className="flex flex-wrap gap-2">
                    {drawing && <Button onClick={finish} disabled={draft.polygon.length < 3}>Cerrar polígono</Button>}
                    <Button variant="primary" disabled={!valid || save.isPending} onClick={() => save.mutate(draft)}>
                      {save.isPending ? "Guardando…" : "Guardar zona"}</Button>
                    {draft.id && <Button variant="danger" disabled={remove.isPending}
                      onClick={() => confirmAction(`¿Eliminar la zona «${draft.name}»?`) && remove.mutate(draft.id!)}>Eliminar</Button>}
                    <Button variant="ghost" onClick={() => { setDraft(null); setDrawing(false); }}>Cancelar</Button>
                  </div>
                )}
              </div>
            </Panel>
          )}
          <Panel title={`Zonas (${zones.data?.length ?? 0})`}>
            <ul className="divide-y divide-ink-700">
              {(zones.data ?? []).map((z, i) => (
                <li key={z.id}>
                  <button onClick={() => select(z)} className={`flex w-full items-center gap-2 px-1 py-2 text-left text-sm hover:bg-ink-850 ${draft?.id === z.id ? "bg-ink-850" : ""}`}>
                    <span className="size-2.5 shrink-0 rounded-sm" style={{ background: z.kind === "restricted" ? "#ff3b3b" : ZONE_COLORS[i % ZONE_COLORS.length] }} />
                    <span className="truncate">{z.name}</span>
                    {z.kind === "restricted" && <Tag tone="alert">restringida</Tag>}
                    <span className="ml-auto truncate text-xs text-ink-400">{profName(z.profile_id) ?? "perfil de la cámara"}</span>
                  </button>
                </li>
              ))}
            </ul>
            {!zones.data?.length && <p className="py-3 text-sm text-ink-400">Sin zonas: toda la imagen usa el perfil por defecto de la cámara.</p>}
          </Panel>
        </div>
      </div>
    </div>
  );
}
