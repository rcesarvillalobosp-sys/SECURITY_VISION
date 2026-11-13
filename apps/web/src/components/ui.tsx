import type { ReactNode } from "react";
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
