import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useNavigate } from "react-router";
import { useAuth } from "../lib/auth";
import { fmtTime, MISSING_LABEL } from "../lib/format";
import { live, useLiveVersion, type LiveEvent } from "../lib/live";

const NAV = [
  { to: "/", label: "Panel", icon: "M3 13h8V3H3zm10 8h8V11h-8zM3 21h8v-6H3zm10-18v6h8V3z" },
  { to: "/monitor", label: "Monitoreo", icon: "M4 5h16v11H4zM8 20h8M12 16v4" },
  { to: "/incidents", label: "Incidentes", icon: "M12 3 2 20h20zM12 10v4m0 3h.01" },
];

function Icon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" className="size-[18px] shrink-0" fill="none" stroke="currentColor" strokeWidth={1.6}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d={d} /></svg>
  );
}

function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);
  return <span className="num text-sm text-ink-300">{now.toLocaleTimeString("es-ES")}</span>;
}

function ConnState() {
  useLiveVersion();
  const s = live.state;
  const color = s === "open" ? "bg-ok" : s === "connecting" ? "bg-review" : "bg-alert";
  const label = s === "open" ? "En vivo" : s === "connecting" ? "Conectando" : "Sin conexión";
  return (
    <span className="flex items-center gap-2 text-xs text-ink-300" title="Conexión de datos en vivo">
      <span className={`size-2 rounded-full ${color}`} />{label}
    </span>
  );
}

/** Alertas instantáneas: incidente confirmado -> aviso emergente. */
function AlertToasts() {
  const [toasts, setToasts] = useState<LiveEvent[]>([]);
  const navigate = useNavigate();
  useEffect(() => live.onEvent((e) => {
    if (e.event !== "incident.confirmed.v1") return;
    setToasts((t) => [e, ...t].slice(0, 4));
    window.setTimeout(() => setToasts((t) => t.filter((x) => x !== e)), 12000);
  }), []);
  if (!toasts.length) return null;
  return (
    <div className="fixed right-4 bottom-4 z-50 flex w-80 flex-col gap-2" role="alert" aria-live="assertive">
      {toasts.map((t) => (
        <button key={t.receivedAt} onClick={() => t.data.incident_id && navigate(`/incidents/${t.data.incident_id}`)}
          className="panel pulse-alert flex flex-col items-start border-alert/70 bg-ink-850 px-3 py-2 text-left">
          <span className="label !text-alert">Incidente confirmado</span>
          <span className="text-sm">{MISSING_LABEL[String(t.data.violation_type)] ?? String(t.data.violation_type)}
            {" "}· confianza {Number(t.data.confidence ?? 0).toFixed(2)}</span>
          <span className="num text-xs text-ink-400">{fmtTime(String(t.data.confirmed_at))}</span>
        </button>
      ))}
    </div>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const { me, logout } = useAuth();
  useEffect(() => {
    live.start();
  }, []);
  return (
    <div className="grid-bg flex h-full min-h-0 flex-col md:flex-row">
      <aside className="flex shrink-0 items-center gap-1 border-b border-ink-700 bg-ink-900 px-3 py-2 md:w-56 md:flex-col md:items-stretch md:border-r md:border-b-0 md:px-3 md:py-4">
        <div className="mr-3 flex items-center gap-2 md:mr-0 md:mb-6 md:px-2">
          <span className="grid size-7 place-items-center rounded bg-signal text-ink-950">
            <svg viewBox="0 0 24 24" className="size-4" fill="currentColor" aria-hidden><path d="M12 2 3 6v6c0 5 4 9 9 10 5-1 9-5 9-10V6z" /></svg>
          </span>
          <span className="hidden text-sm font-semibold tracking-wide sm:inline">SECURITY VISION</span>
        </div>
        <nav className="flex gap-1 md:flex-col">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"}
              className={({ isActive }) => `flex items-center gap-2.5 rounded px-2.5 py-2 text-sm transition ${isActive
                ? "bg-ink-800 text-ink-100 shadow-[inset_2px_0_0_var(--color-signal)]" : "text-ink-300 hover:bg-ink-850 hover:text-ink-100"}`}>
              <Icon d={n.icon} /><span className="hidden sm:inline">{n.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3 md:mt-auto md:ml-0 md:flex-col md:items-stretch md:gap-2 md:border-t md:border-ink-700 md:pt-4">
          <span className="hidden truncate px-1 text-xs text-ink-400 md:block" title={me?.email}>{me?.email}</span>
          <button onClick={logout} className="rounded px-2 py-1 text-left text-xs text-ink-300 hover:bg-ink-800">Cerrar sesión</button>
        </div>
      </aside>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="flex h-11 shrink-0 items-center justify-end gap-5 border-b border-ink-700 bg-ink-900/70 px-4 backdrop-blur">
          <ConnState />
          <Clock />
        </header>
        <main className="min-h-0 flex-1 overflow-auto p-3 sm:p-5">{children}</main>
      </div>
      <AlertToasts />
    </div>
  );
}
