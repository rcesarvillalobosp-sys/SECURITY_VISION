import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, confirmAction, ErrorBox, PageHeader, Panel, Tag } from "../../components/ui";
import { api, apiPut, type ModelEntry, type ModelsState } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { ago, PPE_LABEL } from "../../lib/format";

const METRIC_LABEL: Record<string, string> = {
  mAP50: "mAP50", mAP50_95: "mAP50:95", person_AP50: "AP50 persona", person_AP50_95: "AP50:95 persona",
};

function Metrics({ m }: { m: ModelEntry["metrics"] }) {
  const nums = Object.entries(m).filter(([, v]) => typeof v === "number");
  if (!nums.length) return <p className="text-xs text-ink-400">Sin métricas registradas.</p>;
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap gap-4">
        {nums.map(([k, v]) => (
          <div key={k}><div className="num text-xl leading-none">{Number(v).toFixed(3)}</div>
            <div className="text-[11px] text-ink-400">{METRIC_LABEL[k] ?? k}</div></div>
        ))}
      </div>
      {m.eval_set && <p className="text-[11px] text-ink-400">Conjunto: {String(m.eval_set)}</p>}
      {m.caveat && <p className="text-[11px] text-possible">{String(m.caveat)}</p>}
    </div>
  );
}

export function ModelsAdmin() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["models"], queryFn: () => api.get<ModelsState>("/api/v1/models"), refetchInterval: 5_000 });
  const activate = useMutation({
    mutationFn: (id: string) => apiPut<ModelsState>("/api/v1/models/active", { model_id: id }),
    onSuccess: (d) => qc.setQueryData(["models"], d),
  });
  const s = q.data;
  const loaded = s?.loaded;
  const pending = s && loaded && s.active_model !== loaded.model_id && !loaded.error;

  return (
    <div className="mx-auto max-w-[1200px] space-y-4">
      <PageHeader kicker="Administración" title="Modelos de detección" />
      {(q.error || activate.error) && <ErrorBox error={q.error ?? activate.error} />}
      <Panel title="Estado del worker">
        {!loaded ? (
          <p className="text-sm text-ink-400">Ningún worker ha informado todavía del modelo cargado (¿está detenido?).
            Activo según la configuración: <span className="num text-ink-100">{s?.active_model ?? "ninguno"}</span>.</p>
        ) : (
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
            <span>En uso: <b className="num">{loaded.model_id ?? "ninguno"}</b></span>
            <span className="text-ink-300">Motor: <span className="num">{loaded.engine}</span> · {loaded.device_name ?? loaded.device ?? "—"}</span>
            <span className="text-xs text-ink-400">informado {ago(loaded.at)}</span>
            {pending && <Tag tone="warn">cargando {s!.active_model}…</Tag>}
            {loaded.error && <span className="text-sm text-alert">No se pudo cargar {loaded.requested}: {loaded.error}. Se mantiene el anterior.</span>}
          </div>
        )}
      </Panel>
      <div className="grid gap-3 lg:grid-cols-2">
        {(s?.models ?? []).map((m) => {
          const inUse = loaded?.model_id === m.model_id;
          return (
            <Panel key={m.model_id}
              title={<span className="num normal-case tracking-normal text-ink-100">{m.model_id}</span>}
              actions={<div className="flex gap-1.5">
                {m.active && <Tag tone="signal">activo</Tag>}
                {inUse && <Tag tone="ok">en uso</Tag>}
                {!m.artifact_present && <Tag tone="alert">sin artefacto</Tag>}
              </div>}>
              <div className="space-y-3">
                <div className="text-xs text-ink-300">{m.architecture?.toUpperCase()} · entrada {m.input_size?.join("×")} · umbral {m.score_threshold}</div>
                <div className="flex flex-wrap gap-1">
                  {m.canonical_classes.map((c) => <Tag key={c}>{PPE_LABEL[c] ?? c}</Tag>)}
                </div>
                <Metrics m={m.metrics} />
                <dl className="grid grid-cols-[7rem_1fr] gap-x-3 gap-y-1 text-xs">
                  <dt className="text-ink-400">Licencia</dt><dd>{m.license}</dd>
                  <dt className="text-ink-400">Pesos</dt><dd>{m.weights_license}</dd>
                  {m.dataset_ref && <><dt className="text-ink-400">Datos</dt><dd>{m.dataset_ref}</dd></>}
                </dl>
                {m.notes && <p className="text-[11px] leading-snug text-ink-400">{m.notes}</p>}
                {m.error && <p className="text-xs text-alert">{m.error}</p>}
                {can("models:write") && !m.active && (
                  <Button disabled={!m.artifact_present || activate.isPending}
                    onClick={() => confirmAction(`¿Activar ${m.model_id}? El worker lo cargará y sustituirá al actual sin detener las cámaras.`) && activate.mutate(m.model_id)}>
                    Activar</Button>
                )}
              </div>
            </Panel>
          );
        })}
      </div>
    </div>
  );
}
