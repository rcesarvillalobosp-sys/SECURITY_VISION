import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Button, ErrorBox, Field, Input, PageHeader, Panel, Tag } from "../components/ui";
import { api, setToken } from "../lib/api";
import { useAuth } from "../lib/auth";
import { ROLE_LABEL } from "../lib/format";

export function Account() {
  const { me } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const change = useMutation({
    mutationFn: () => api.post("/api/v1/me/password", { current_password: current, new_password: next }),
    // El servidor cierra todas las sesiones (también esta): hay que volver a entrar
    onSuccess: () => { setToken(null); window.location.assign("/"); },
  });
  const mismatch = repeat.length > 0 && next !== repeat;

  return (
    <div className="mx-auto max-w-xl space-y-4">
      <PageHeader kicker="Cuenta" title={me?.email ?? ""} />
      <Panel title="Roles">
        <div className="flex flex-wrap gap-1.5">{me?.roles.map((r) => <Tag key={r} tone="signal">{ROLE_LABEL[r] ?? r}</Tag>)}</div>
      </Panel>
      <Panel title="Cambiar contraseña">
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (!mismatch) change.mutate(); }}>
          {change.error && <ErrorBox error={change.error} />}
          <Field label="Contraseña actual"><Input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} /></Field>
          <Field label="Nueva contraseña" hint="Mínimo 12 caracteres y 3 de: minúsculas, mayúsculas, dígitos, símbolos">
            <Input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} /></Field>
          <Field label="Repetir la nueva contraseña" hint={mismatch ? <span className="text-alert">No coinciden</span> : undefined}>
            <Input type="password" autoComplete="new-password" value={repeat} onChange={(e) => setRepeat(e.target.value)} /></Field>
          <p className="text-[11px] text-ink-400">Al cambiarla se cierran todas tus sesiones, también esta: tendrás que volver a entrar.</p>
          <Button variant="primary" disabled={!current || !next || mismatch || change.isPending}>
            {change.isPending ? "Cambiando…" : "Cambiar contraseña"}</Button>
        </form>
      </Panel>
    </div>
  );
}
