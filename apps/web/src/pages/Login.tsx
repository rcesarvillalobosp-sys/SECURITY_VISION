import { useState, type FormEvent } from "react";
import { useAuth } from "../lib/auth";

export function Login() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo iniciar sesión");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid-bg grid min-h-full place-items-center p-4">
      <form onSubmit={submit} className="panel w-full max-w-sm overflow-hidden">
        <div className="h-1 bg-[repeating-linear-gradient(135deg,var(--color-signal)_0_12px,#070a0e_12px_24px)]" />
        <div className="space-y-5 p-6">
          <div>
            <div className="label">Plataforma de seguridad</div>
            <h1 className="mt-1 text-xl font-semibold tracking-wide">SECURITY VISION</h1>
          </div>
          <label className="block">
            <span className="label">Correo</span>
            <input type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded border border-ink-600 bg-ink-850 px-3 py-2 text-sm outline-none focus:border-signal" />
          </label>
          <label className="block">
            <span className="label">Contraseña</span>
            <input type="password" required autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded border border-ink-600 bg-ink-850 px-3 py-2 text-sm outline-none focus:border-signal" />
          </label>
          {error && <p className="rounded border border-alert/40 bg-alert/10 px-3 py-2 text-sm text-alert" role="alert">{error}</p>}
          <button disabled={busy} className="w-full rounded bg-signal py-2 text-sm font-semibold text-ink-950 transition hover:brightness-110 disabled:opacity-60">
            {busy ? "Entrando…" : "Entrar"}
          </button>
          <p className="text-xs text-ink-400">Acceso restringido y auditado. Las imágenes contienen datos personales.</p>
        </div>
      </form>
    </div>
  );
}
