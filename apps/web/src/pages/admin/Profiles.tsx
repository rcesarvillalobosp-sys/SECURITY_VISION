import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button, Check, confirmAction, Drawer, ErrorBox, Field, Input, PageHeader, Panel, Tag } from "../../components/ui";
import { api, type Catalog, type Profile } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { PPE_LABEL, THRESHOLD_INFO } from "../../lib/format";

type Th = Record<string, number | boolean>;

function ProfileForm({ profile, catalog, onClose }: { profile?: Profile; catalog: Catalog; onClose: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState(profile?.name ?? "");
  const [ppe, setPpe] = useState<string[]>(profile?.required_ppe ?? ["helmet", "safety_vest"]);
  const [th, setTh] = useState<Th>({ ...catalog.default_thresholds, ...(profile?.thresholds ?? {}) });
  const [advanced, setAdvanced] = useState(false);
  const changed = Object.keys(th).filter((k) => th[k] !== catalog.default_thresholds[k]);

  const save = useMutation({
    mutationFn: () => {
      // Se envía el juego completo: restaurar un valor por defecto también se guarda
      const body = { name: name.trim(), required_ppe: ppe, thresholds: th };
      return profile ? api.patch<Profile>(`/api/v1/security-profiles/${profile.id}`, body)
        : api.post<Profile>("/api/v1/security-profiles", body);
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["profiles"] }); onClose(); },
  });

  return (
    <Drawer wide title={profile ? `Editar perfil · v${profile.version}` : "Nuevo perfil"} onClose={onClose}
      footer={<>
        <Button variant="ghost" onClick={onClose}>Cancelar</Button>
        <Button variant="primary" disabled={save.isPending || !name.trim() || !ppe.length} onClick={() => save.mutate()}>
          {save.isPending ? "Guardando…" : "Guardar"}</Button>
      </>}>
      {save.error && <ErrorBox error={save.error} />}
      <Field label="Nombre"><Input value={name} maxLength={100} onChange={(e) => setName(e.target.value)} autoFocus /></Field>
      <div>
        <div className="mb-2 text-xs font-medium text-ink-300">EPP exigido</div>
        <div className="flex flex-wrap gap-x-5 gap-y-2">
          {catalog.evaluable_ppe.map((p) => (
            <Check key={p} label={PPE_LABEL[p] ?? p} checked={ppe.includes(p)}
              onChange={(v) => setPpe((cur) => (v ? [...cur, p] : cur.filter((x) => x !== p)))} />
          ))}
        </div>
        {ppe.includes("safety_boot") && (
          <p className="mt-2 text-[11px] text-possible">«Botas» significa calzado de trabajo tipo bota visible; no certifica protección.
            El modelo piloto no tiene entrenada la detección de «sin botas»: su incumplimiento casi nunca podrá confirmarse.</p>
        )}
      </div>
      <div className="rounded border border-ink-700 p-3 text-xs text-ink-300">
        El motor nunca confirma un incumplimiento con un solo fotograma: exige ausencia sostenida y detecciones explícitas de
        «sin EPP». Los valores por defecto son conservadores; cámbialos solo con pruebas en tus cámaras.
      </div>
      <button type="button" onClick={() => setAdvanced((a) => !a)} className="text-sm text-signal hover:underline">
        {advanced ? "Ocultar" : "Mostrar"} umbrales del motor {changed.length ? `(${changed.length} modificados)` : ""}
      </button>
      {advanced && (
        <div className="grid gap-3 sm:grid-cols-2">
          {Object.keys(catalog.default_thresholds).map((k) => {
            const info = THRESHOLD_INFO[k] ?? { label: k, help: "" };
            const def = catalog.default_thresholds[k];
            const v = th[k];
            const mod = v !== def;
            if (typeof def === "boolean") {
              return (
                <div key={k} className="flex flex-col gap-1">
                  <Check checked={!!v} onChange={(x) => setTh({ ...th, [k]: x })} label={<span className={mod ? "text-signal" : ""}>{info.label}</span>} />
                  <span className="text-[11px] text-ink-400">{info.help} · por defecto {def ? "sí" : "no"}</span>
                </div>
              );
            }
            return (
              <Field key={k} label={<span className={mod ? "text-signal" : ""}>{info.label}</span>}
                hint={`${info.help} · por defecto ${def}`}>
                <Input type="number" step={info.step ?? 1} value={String(v)}
                  onChange={(e) => setTh({ ...th, [k]: e.target.value === "" ? def : Number(e.target.value) })} className="num" />
              </Field>
            );
          })}
          {changed.length > 0 && <Button type="button" variant="ghost" onClick={() => setTh({ ...catalog.default_thresholds })}>Restaurar valores por defecto</Button>}
        </div>
      )}
      {profile && <p className="text-[11px] text-ink-400">Guardar crea la versión v{profile.version + 1}. Los workers recargan las reglas sin cortar el vídeo
        (el estado temporal de las personas se reinicia). Los incidentes guardan la versión con la que se confirmaron.</p>}
    </Drawer>
  );
}

export function ProfilesAdmin() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const writable = can("rules:write");
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => api.get<Catalog>("/api/v1/security-profiles/catalog") });
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: () => api.get<Profile[]>("/api/v1/security-profiles") });
  const [editing, setEditing] = useState<Profile | "new" | null>(null);
  const remove = useMutation({
    mutationFn: (p: Profile) => api.del(`/api/v1/security-profiles/${p.id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["profiles"] }),
  });
  const defaults = catalog.data?.default_thresholds ?? {};

  return (
    <div className="mx-auto max-w-[1200px] space-y-4">
      <PageHeader kicker="Administración" title="Perfiles de seguridad"
        actions={writable && <Button variant="primary" disabled={!catalog.data} onClick={() => setEditing("new")}>Nuevo perfil</Button>} />
      {(profiles.error || remove.error) && <ErrorBox error={profiles.error ?? remove.error} />}
      <div className="grid gap-3 md:grid-cols-2">
        {(profiles.data ?? []).map((p) => {
          const custom = Object.keys(p.thresholds).filter((k) => p.thresholds[k] !== defaults[k]);
          return (
            <Panel key={p.id} title={<span className="normal-case tracking-normal text-ink-100">{p.name}</span>}
              actions={<span className="num text-xs text-ink-400">v{p.version}</span>}>
              <div className="flex flex-wrap gap-1.5">
                {p.required_ppe.map((x) => <Tag key={x} tone="signal">{PPE_LABEL[x] ?? x}</Tag>)}
              </div>
              <p className="mt-2 text-xs text-ink-400">
                {custom.length ? `Umbrales propios: ${custom.map((k) => `${THRESHOLD_INFO[k]?.label ?? k} = ${p.thresholds[k]}`).join(" · ")}`
                  : "Umbrales por defecto del motor"}
              </p>
              {writable && (
                <div className="mt-3 flex gap-2">
                  <Button className="!py-1 text-xs" onClick={() => setEditing(p)} disabled={!catalog.data}>Editar</Button>
                  <Button variant="ghost" className="!py-1 text-xs !text-alert"
                    onClick={() => confirmAction(`¿Eliminar el perfil «${p.name}»?`) && remove.mutate(p)}>Eliminar</Button>
                </div>
              )}
            </Panel>
          );
        })}
      </div>
      {editing && catalog.data && <ProfileForm profile={editing === "new" ? undefined : editing} catalog={catalog.data} onClose={() => setEditing(null)} />}
    </div>
  );
}
