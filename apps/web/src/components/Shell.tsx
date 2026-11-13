import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useNavigate } from "react-router";
import { useAuth } from "../lib/auth";
import { fmtTime, MISSING_LABEL } from "../lib/format";
import { live, useLiveVersion, type LiveEvent } from "../lib/live";

interface NavItem { to: string; label: string; icon: string; perm?: string }
const NAV: NavItem[] = [
  { to: "/", label: "Panel", icon: "M3 13h8V3H3zm10 8h8V11h-8zM3 21h8v-6H3zm10-18v6h8V3z" },
  { to: "/monitor", label: "Monitoreo", icon: "M4 5h16v11H4zM8 20h8M12 16v4" },
  { to: "/incidents", label: "Incidentes", icon: "M12 3 2 20h20zM12 10v4m0 3h.01" },
  { to: "/reports", label: "Reportes", icon: "M6 3h9l4 4v14H6zM14 3v5h5M9 13h7M9 17h5", perm: "reports:read" },
];
/** Administración: solo se muestra lo que el rol permite (el servidor lo vuelve a comprobar). */
const ADMIN: NavItem[] = [
  { to: "/admin/cameras", label: "Cámaras y zonas", icon: "M3 7h12v10H3zM15 10l6-3v10l-6-3", perm: "cameras:write" },
  { to: "/admin/profiles", label: "Perfiles EPP", icon: "M12 3 4 6v6c0 4.5 3.4 8.2 8 9 4.6-.8 8-4.5 8-9V6zM9 12l2 2 4-4", perm: "rules:write" },
  { to: "/admin/models", label: "Modelos", icon: "M12 3 3 8l9 5 9-5zM3 13l9 5 9-5M3 18l9 5 9-5", perm: "cameras:read" },
  { to: "/admin/alerts", label: "Alertas", icon: "M18 16V11a6 6 0 1 0-12 0v5l-2 2h16zM10 21h4", perm: "alerts:write" },
  { to: "/admin/users", label: "Usuarios", icon: "M16 19v-1a4 4 0 0 0-8 0v1M12 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM20 19v-1a3 3 0 0 0-2-2.8M17 5.3a3 3 0 0 1 0 5.4", perm: "users:read" },
  { to: "/admin/audit", label: "Auditoría", icon: "M4 4h16v16H4zM8 9h8M8 13h8M8 17h4", perm: "audit:read" },
];

function NavItems({ items }: { items: NavItem[] }) {
  return (
    <>
      {items.map((n) => (
        <NavLink key={n.to} to={n.to} end={n.to === "/"} title={n.label}
          className={({ isActive }) => `flex shrink-0 items-center gap-2.5 rounded px-2.5 py-2 text-sm transition ${isActive
            ? "bg-ink-800 text-ink-100 shadow-[inset_2px_0_0_var(--color-signal)]" : "text-ink-300 hover:bg-ink-850 hover:text-ink-100"}`}>
          <Icon d={n.icon} /><span className="hidden lg:inline">{n.label}</span>
        </NavLink>
      ))}
    </>
  );
}

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
    <div className="fixed top-14 right-4 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2" role="alert" aria-live="assertive">
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
  const { me, logout, can } = useAuth();
  const main = NAV.filter((n) => !n.perm || can(n.perm));
  const admin = ADMIN.filter((n) => !n.perm || can(n.perm));
  useEffect(() => {
    live.start();
  }, []);
  return (
    <div className="grid-bg flex h-full min-h-0 flex-col md:flex-row">
      <aside className="flex shrink-0 items-center gap-1 border-b border-ink-700 bg-ink-900 px-3 py-2 md:w-16 lg:w-56 md:flex-col md:items-stretch md:border-r md:border-b-0 md:px-3 md:py-4">
        <div className="mr-3 flex items-center gap-2 md:mr-0 md:mb-6 md:px-2">
          <span className="grid size-7 place-items-center rounded bg-signal text-ink-950">
            <svg viewBox="0 0 24 24" className="size-4" fill="currentColor" aria-hidden><path d="M12 2 3 6v6c0 5 4 9 9 10 5-1 9-5 9-10V6z" /></svg>
          </span>
          <span className="hidden text-sm font-semibold tracking-wide sm:inline">SECURITY VISION</span>
        </div>
        <nav className="flex min-w-0 gap-1 overflow-x-auto md:flex-col md:overflow-visible" aria-label="Navegación principal">
          <NavItems items={main} />
          {admin.length > 0 && (
            <>
              <span className="mx-1 w-px shrink-0 self-stretch bg-ink-700 md:mx-0 md:mt-4 md:mb-1 md:h-auto md:w-auto md:bg-transparent md:px-2.5">
                <span className="label hidden lg:inline">Administración</span></span>
              <NavItems items={admin} />
            </>
          )}
        </nav>
        <div className="ml-auto flex items-center gap-3 md:mt-auto md:ml-0 md:flex-col md:items-stretch md:gap-2 md:border-t md:border-ink-700 md:pt-4">
          <NavLink to="/account" className="hidden truncate rounded px-1 py-0.5 text-xs text-ink-400 hover:text-ink-100 md:block" title="Mi cuenta">{me?.email}</NavLink>
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
