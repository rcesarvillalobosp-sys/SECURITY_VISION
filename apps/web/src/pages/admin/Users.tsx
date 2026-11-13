import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button, Check, confirmAction, Drawer, ErrorBox, Field, Input, PageHeader, Tag } from "../../components/ui";
import { api, apiPut, type Page, type Role, type User } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { ago, ROLE_LABEL } from "../../lib/format";

const PWD_HINT = "Mínimo 12 caracteres y 3 de: minúsculas, mayúsculas, dígitos, símbolos";

function UserForm({ user, roles, onClose }: { user?: User; roles: Role[]; onClose: () => void }) {
  const qc = useQueryClient();
  const { me } = useAuth();
  const [email, setEmail] = useState(user?.email ?? "");
  const [name, setName] = useState(user?.display_name ?? "");
  const [password, setPassword] = useState("");
  const [sel, setSel] = useState<string[]>(user?.roles ?? ["viewer"]);
  const [active, setActive] = useState(user?.is_active ?? true);
  const self = user?.id === me?.user_id;

  const save = useMutation({
    mutationFn: async () => {
      if (!user) return api.post<User>("/api/v1/users", { email: email.trim(), display_name: name.trim(), password, roles: sel });
      if (name.trim() !== user.display_name || active !== user.is_active) {
        await api.patch<User>(`/api/v1/users/${user.id}`, { display_name: name.trim(), is_active: active });
      }
      if ([...sel].sort().join() !== [...user.roles].sort().join()) await apiPut<User>(`/api/v1/users/${user.id}/roles`, { roles: sel });
      if (password) await api.post(`/api/v1/users/${user.id}/password`, { password });
      return user;
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["users"] }); onClose(); },
  });

  return (
    <Drawer title={user ? `Editar ${user.email}` : "Nuevo usuario"} onClose={onClose}
      footer={<>
        <Button variant="ghost" onClick={onClose}>Cancelar</Button>
        <Button variant="primary" disabled={save.isPending || !name.trim() || (!user && (!email.trim() || !password)) || !sel.length}
          onClick={() => save.mutate()}>{save.isPending ? "Guardando…" : "Guardar"}</Button>
      </>}>
      {save.error && <ErrorBox error={save.error} />}
      {!user && <Field label="Email"><Input type="email" value={email} autoComplete="off" onChange={(e) => setEmail(e.target.value)} autoFocus /></Field>}
      <Field label="Nombre visible"><Input value={name} maxLength={200} onChange={(e) => setName(e.target.value)} /></Field>
      <Field label={user ? "Nueva contraseña (opcional)" : "Contraseña inicial"}
        hint={user ? `${PWD_HINT}. Restablecerla cierra todas sus sesiones.` : PWD_HINT}>
        <Input type="password" value={password} autoComplete="new-password" onChange={(e) => setPassword(e.target.value)} />
      </Field>
      <div>
        <div className="mb-2 text-xs font-medium text-ink-300">Roles</div>
        <div className="space-y-2">
          {roles.map((r) => (
            <div key={r.name}>
              <Check label={<span><b className="font-medium">{ROLE_LABEL[r.name] ?? r.name}</b> <span className="text-ink-400">· {r.description}</span></span>}
                checked={sel.includes(r.name)} disabled={self && r.name === "admin"}
                onChange={(v) => setSel((s) => (v ? [...s, r.name] : s.filter((x) => x !== r.name)))} />
              <div className="ml-6 text-[11px] text-ink-400">{r.permissions.join(", ")}</div>
            </div>
          ))}
        </div>
        {user && <p className="mt-2 text-[11px] text-ink-400">Cambiar los roles cierra las sesiones del usuario para que el cambio sea inmediato.</p>}
      </div>
      {user && !self && <Check checked={active} onChange={setActive} label="Cuenta activa (desactivarla cierra sus sesiones al instante)" />}
    </Drawer>
  );
}

export function UsersAdmin() {
  const { can } = useAuth();
  const writable = can("users:write");
  const users = useQuery({ queryKey: ["users"], queryFn: () => api.get<Page<User>>("/api/v1/users?limit=200") });
  const roles = useQuery({ queryKey: ["roles"], queryFn: () => api.get<Role[]>("/api/v1/roles") });
  const [editing, setEditing] = useState<User | "new" | null>(null);
  const qc = useQueryClient();
  const toggle = useMutation({
    mutationFn: (u: User) => api.patch<User>(`/api/v1/users/${u.id}`, { is_active: !u.is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });

  return (
    <div className="mx-auto max-w-[1200px] space-y-4">
      <PageHeader kicker="Administración" title="Usuarios y roles"
        actions={writable && <Button variant="primary" onClick={() => setEditing("new")} disabled={!roles.data}>Nuevo usuario</Button>} />
      {(users.error || toggle.error) && <ErrorBox error={users.error ?? toggle.error} />}
      <div className="panel overflow-x-auto">
        <table className="w-full min-w-[680px] text-sm">
          <thead className="border-b border-ink-700 text-left">
            <tr className="label"><th className="px-4 py-2 font-medium">Usuario</th><th className="px-4 py-2 font-medium">Roles</th>
              <th className="px-4 py-2 font-medium">Último acceso</th><th className="px-4 py-2 font-medium">Estado</th><th /></tr>
          </thead>
          <tbody className="divide-y divide-ink-700">
            {(users.data?.items ?? []).map((u) => (
              <tr key={u.id} className={u.is_active ? "" : "opacity-60"}>
                <td className="px-4 py-2.5"><div className="font-medium">{u.display_name}</div><div className="text-xs text-ink-400">{u.email}</div></td>
                <td className="px-4 py-2.5"><div className="flex flex-wrap gap-1">{u.roles.map((r) => <Tag key={r} tone={r === "admin" ? "signal" : "muted"}>{ROLE_LABEL[r] ?? r}</Tag>)}</div></td>
                <td className="px-4 py-2.5 text-xs text-ink-300">{u.last_login_at ? ago(u.last_login_at) : "nunca"}</td>
                <td className="px-4 py-2.5">{u.is_active ? <Tag tone="ok">activa</Tag> : <Tag tone="alert">desactivada</Tag>}</td>
                <td className="px-4 py-2.5">
                  {writable && <div className="flex justify-end gap-1">
                    <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={() => setEditing(u)} disabled={!roles.data}>Editar</Button>
                    <Button variant="ghost" className="!px-2 !py-1 text-xs"
                      onClick={() => confirmAction(u.is_active ? `¿Desactivar a ${u.email}? Se cerrarán sus sesiones.` : `¿Reactivar a ${u.email}?`) && toggle.mutate(u)}>
                      {u.is_active ? "Desactivar" : "Reactivar"}</Button>
                  </div>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editing && roles.data && <UserForm user={editing === "new" ? undefined : editing} roles={roles.data} onClose={() => setEditing(null)} />}
    </div>
  );
}
