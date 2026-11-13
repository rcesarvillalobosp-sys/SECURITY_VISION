import { useEffect, type ReactNode } from "react";
import { INCIDENT_STATUS_LABEL, STATUS_COLOR, STATUS_LABEL } from "../lib/format";

export function Panel({ title, actions, children, className = "" }:
  { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`panel min-w-0 ${className}`}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-ink-700 px-4 py-2.5">
          <h2 className="label">{title}</h2>
          {actions}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Kpi({ label, value, sub, tone = "default", pulse = false }:
  { label: string; value: ReactNode; sub?: ReactNode; tone?: "default" | "ok" | "warn" | "alert" | "muted"; pulse?: boolean }) {
  const toneClass = { default: "text-ink-100", ok: "text-ok", warn: "text-possible", alert: "text-alert",
    muted: "text-ink-300" }[tone];
  return (
    <div className="panel relative overflow-hidden px-4 py-3">
      <span className={`absolute inset-y-0 left-0 w-[3px] ${tone === "default" ? "bg-ink-600" : tone === "ok" ? "bg-ok"
        : tone === "warn" ? "bg-possible" : tone === "alert" ? "bg-alert" : "bg-ink-600"}`} />
      <div className="label">{label}</div>
      <div className={`num mt-1 flex items-center gap-2 text-3xl font-medium leading-none ${toneClass}`}>
        {value}
        {pulse && <span className="pulse-alert inline-block size-2.5 rounded-full bg-alert" />}
      </div>
      {sub && <div className="mt-1.5 text-xs text-ink-400">{sub}</div>}
    </div>
  );
}

export function StatusPill({ status }: { status: string | null | undefined }) {
  const s = status ?? "NO_VERIFICABLE";
  const color = STATUS_COLOR[s] ?? STATUS_COLOR.NO_VERIFICABLE;
  return (
    <span className="inline-flex items-center gap-1.5 rounded border px-1.5 py-0.5 text-[11px] font-medium"
      style={{ borderColor: `${color}66`, color, background: `${color}14` }}>
      <span className="size-1.5 rounded-full" style={{ background: color }} />
      {STATUS_LABEL[s] ?? s}
    </span>
  );
}

const REVIEW_COLOR: Record<string, string> = {
  PENDIENTE: "#ff8c1a", EN_REVISION: "#f2c94c", CONFIRMADO: "#ff3b3b", DESCARTADO: "#8a94a3", RESUELTO: "#2bd17e",
};

export function ReviewPill({ status }: { status: string }) {
  const color = REVIEW_COLOR[status] ?? "#8a94a3";
  return (
    <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-semibold tracking-wide"
      style={{ color, background: `${color}1f`, border: `1px solid ${color}55` }}>
      {INCIDENT_STATUS_LABEL[status] ?? status}
    </span>
  );
}

export function CamDot({ status }: { status: string | null }) {
  const ok = status === "streaming";
  const warn = status === "connecting" || status === "reconnecting";
  return (
    <span className={`inline-block size-2 rounded-full ${ok ? "bg-ok" : warn ? "bg-review" : "bg-alert"}`}
      title={status ?? "desconocido"} />
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="flex min-h-24 items-center justify-center text-sm text-ink-400">{children}</div>;
}

export function ErrorBox({ error }: { error: unknown }) {
  return (
    <div className="rounded border border-alert/40 bg-alert/10 px-3 py-2 text-sm text-alert">
      {error instanceof Error ? error.message : String(error)}
    </div>
  );
}

export function Button({ children, variant = "default", ...rest }:
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "default" | "primary" | "danger" | "ghost" }) {
  const cls = {
    default: "border-ink-600 bg-ink-800 text-ink-100 hover:bg-ink-700",
    primary: "border-signal bg-signal text-ink-950 hover:brightness-110",
    danger: "border-alert/60 bg-alert/15 text-alert hover:bg-alert/25",
    ghost: "border-transparent bg-transparent text-ink-300 hover:bg-ink-800 hover:text-ink-100",
  }[variant];
  return (
    <button {...rest}
      className={`inline-flex items-center justify-center gap-2 rounded border px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${cls} ${rest.className ?? ""}`}>
      {children}
    </button>
  );
}

// ---------------------------------------------------------------- formularios (Fase 8)
const FIELD = "w-full min-w-0 rounded border border-ink-600 bg-ink-850 px-2 py-1.5 text-sm outline-none focus:border-signal disabled:opacity-60";

export function Field({ label, hint, children, className = "" }:
  { label: ReactNode; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={`flex min-w-0 flex-col gap-1 ${className}`}>
      <span className="text-xs font-medium text-ink-300">{label}</span>
      {children}
      {hint && <span className="text-[11px] leading-snug text-ink-400">{hint}</span>}
    </label>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${FIELD} ${props.className ?? ""}`} />;
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={`${FIELD} ${props.className ?? ""}`} />;
}

export function Check({ checked, onChange, label, disabled }:
  { checked: boolean; onChange: (v: boolean) => void; label: ReactNode; disabled?: boolean }) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2 text-sm select-none">
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)}
        className="size-4 accent-[var(--color-signal)]" />
      {label}
    </label>
  );
}

/** Panel lateral para formularios de alta/edición. Esc cierra. */
export function Drawer({ title, onClose, children, footer, wide = false }:
  { title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-ink-950/70 backdrop-blur-[2px]" onMouseDown={onClose}>
      <aside role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : undefined}
        onMouseDown={(e) => e.stopPropagation()}
        className={`flex h-full w-full flex-col border-l border-ink-700 bg-ink-900 shadow-2xl ${wide ? "max-w-3xl" : "max-w-lg"}`}>
        <header className="flex items-center justify-between border-b border-ink-700 px-4 py-3">
          <h2 className="text-sm font-semibold">{title}</h2>
          <button onClick={onClose} aria-label="Cerrar" className="rounded px-2 py-1 text-ink-300 hover:bg-ink-800">✕</button>
        </header>
        <div className="min-h-0 flex-1 space-y-4 overflow-auto p-4">{children}</div>
        {footer && <footer className="flex justify-end gap-2 border-t border-ink-700 px-4 py-3">{footer}</footer>}
      </aside>
    </div>
  );
}

export function PageHeader({ kicker, title, actions }: { kicker: ReactNode; title: string; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div><div className="label">{kicker}</div><h1 className="text-lg font-semibold">{title}</h1></div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Tag({ children, tone = "muted" }: { children: ReactNode; tone?: "muted" | "ok" | "warn" | "alert" | "signal" }) {
  const cls = { muted: "border-ink-600 text-ink-300", ok: "border-ok/50 text-ok", warn: "border-possible/50 text-possible",
    alert: "border-alert/50 text-alert", signal: "border-signal/60 text-signal" }[tone];
  return <span className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] font-medium ${cls}`}>{children}</span>;
}

/** Confirmación explícita para acciones destructivas. */
export function confirmAction(message: string): boolean {
  return window.confirm(message);
}
