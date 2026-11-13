/**
 * Cliente de la API.
 * - El token de acceso vive SOLO en memoria (no en localStorage: mitiga robo por XSS).
 * - El refresh token es una cookie httpOnly que el navegador envía a /api/v1/auth.
 * - Un 401 dispara UNA renovación compartida (single-flight) y reintenta la petición una vez.
 */

export class ApiError extends Error {
  constructor(public status: number, message: string, public body?: unknown) {
    super(message);
  }
}

type TokenListener = (token: string | null) => void;

let accessToken: string | null = null;
let refreshing: Promise<string | null> | null = null;
const listeners = new Set<TokenListener>();

export function getToken(): string | null {
  return accessToken;
}

export function setToken(token: string | null): void {
  accessToken = token;
  listeners.forEach((l) => l(token));
}

export function onTokenChange(l: TokenListener): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}

/** Esperas entre reintentos de la renovación cuando el servidor no responde (reinicio, 502...). */
export const REFRESH_RETRY_MS = [1000, 2000, 4000];
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function refreshToken(): Promise<string | null> {
  if (!refreshing) {
    refreshing = (async () => {
      try {
        for (let attempt = 0; ; attempt++) {
          let r: Response | null = null;
          try {
            r = await fetch("/api/v1/auth/refresh", { method: "POST", credentials: "same-origin" });
          } catch {
            r = null; // red caída o servidor reiniciándose
          }
          // Solo un rechazo explícito (4xx) significa "sesión no válida". Un fallo transitorio (sin
          // respuesta o 5xx) se reintenta: si no, reiniciar la API sacaría a todos los usuarios.
          if (r && r.status < 500) {
            if (!r.ok) {
              setToken(null);
              return null;
            }
            const body = (await r.json()) as { access_token: string };
            setToken(body.access_token);
            return body.access_token;
          }
          if (attempt >= REFRESH_RETRY_MS.length) return null;
          await sleep(REFRESH_RETRY_MS[attempt]);
        }
      } finally {
        refreshing = null;
      }
    })();
  }
  return refreshing;
}

async function detail(r: Response): Promise<string> {
  try {
    const b = await r.json();
    if (typeof b?.detail === "string") return b.detail;
    if (Array.isArray(b?.detail)) return b.detail.map((d: { msg?: string }) => d.msg).join("; ");
  } catch {
    /* cuerpo no JSON */
  }
  return `${r.status} ${r.statusText}`;
}

export async function request<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const r = await fetch(path, { ...init, headers, credentials: "same-origin" });
  if (r.status === 401 && retry && !path.startsWith("/api/v1/auth/")) {
    const t = await refreshToken();
    if (t) return request<T>(path, init, false);
  }
  if (!r.ok) throw new ApiError(r.status, await detail(r));
  if (r.status === 204) return undefined as T;
  const ct = r.headers.get("content-type") ?? "";
  return (ct.includes("application/json") ? r.json() : r.blob()) as Promise<T>;
}

export const api = {
  get: <T>(p: string) => request<T>(p),
  post: <T>(p: string, body?: unknown) => request<T>(p, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(p: string, body: unknown) => request<T>(p, { method: "PATCH", body: JSON.stringify(body) }),
  del: <T>(p: string) => request<T>(p, { method: "DELETE" }),
};

// ---------------------------------------------------------------- tipos de la API
export interface Me { user_id: string; email: string; roles: string[]; permissions: string[] }
export interface Camera {
  id: string; name: string; source_type: string; source_uri: string; has_credentials: boolean;
  analysis_fps: number; enabled: boolean; status: string | null; status_at: string | null;
  last_error: string | null; webrtc_url: string | null; default_profile_id: string | null;
  location: Record<string, string>;
}
export type IncidentStatus = "PENDIENTE" | "EN_REVISION" | "CONFIRMADO" | "DESCARTADO" | "RESUELTO";
export interface Incident {
  id: string; camera_id: string | null; camera_name: string; track_id: number; violation_type: string;
  status: IncidentStatus; confidence: number; started_at: string | null; confirmed_at: string;
  ended_at: string | null; end_reason: string | null; model_id: string | null;
}
export interface Evidence {
  id: string; kind: string; url: string | null; sha256: string; width: number | null; height: number | null;
  captured_at: string; frame_id: number | null; purged: boolean; meta: Record<string, unknown>;
}
export interface IncidentDetail extends Incident {
  details: Record<string, number>;
  evidences: Evidence[];
  detections: Array<{ class_name: string; confidence: number; track_id: number | null; bbox: number[];
    frame_id: number; frame_ts: string; model_id: string; inference_ms: number; evidence_id: string | null }>;
  history: Array<{ action: string; from_status: string | null; to_status: string | null; note: string | null;
    actor_id: string | null; at: string }>;
  comments: Array<{ id: string; body: string; author_id: string | null; at: string }>;
}
export interface Page<T> { items: T[]; total: number; offset: number; limit: number }
export interface Summary {
  cameras: { total: number; enabled: number; streaming: number; disconnected: number };
  incidents: { today: number; pending: number; discarded_today: number; today_by_type: Record<string, number> };
  compliance_today_pct: number | null; avg_persons_per_frame_today: number | null; persons_now: number;
  generated_at: string;
}
export interface SeriesPoint {
  t: string; person_frames: number; max_persons: number; compliant: number; in_review: number; possible: number;
  confirmed: number; unverifiable: number; compliance_pct: number | null;
}
export interface Series { range: string; step: string; compliance: SeriesPoint[];
  incidents_by_day: Array<{ day: string; type: string; n: number }> }

export const apiPut = <T>(p: string, body: unknown) => request<T>(p, { method: "PUT", body: JSON.stringify(body) });

/** Descarga autenticada (el token no va en la URL): blob -> enlace temporal. */
export async function download(path: string, fallbackName: string): Promise<void> {
  const headers = new Headers();
  const send = async () => {
    const t = getToken();
    if (t) headers.set("Authorization", `Bearer ${t}`);
    return fetch(path, { headers, credentials: "same-origin" });
  };
  let r = await send();
  if (r.status === 401 && (await refreshToken())) r = await send();
  if (!r.ok) throw new ApiError(r.status, await detail(r));
  const name = /filename="([^"]+)"/.exec(r.headers.get("content-disposition") ?? "")?.[1] ?? fallbackName;
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

// ---------------------------------------------------------------- administración (Fase 8)
export interface User {
  id: string; email: string; display_name: string; is_active: boolean; roles: string[]; last_login_at: string | null;
}
export interface Role { name: string; description: string; permissions: string[] }
export interface Profile { id: string; name: string; required_ppe: string[]; thresholds: Record<string, number | boolean>; version: number }
export interface Zone { id: string; name: string; kind: "ppe" | "restricted"; polygon: number[][]; profile_id: string | null }
export interface Catalog { evaluable_ppe: string[]; default_thresholds: Record<string, number | boolean> }
export interface Probe { ok: boolean; elapsed_ms: number; error: string | null; codec?: string | null; width?: number | null;
  height?: number | null; nominal_fps?: number | null }
export interface ModelEntry {
  model_id: string; architecture: string | null; labels: string[]; canonical_classes: string[]; input_size: number[] | null;
  score_threshold: number | null; license: string | null; weights_license: string | null; weights_source: string | null;
  dataset_ref: string | null; notes: string | null; metrics: Record<string, string | number>; artifact_present: boolean;
  error: string | null; active: boolean;
}
export interface ModelsState {
  active_model: string | null; models: ModelEntry[];
  loaded: { model_id: string | null; requested: string; error: string | null; engine: string; device: string | null;
    device_name: string | null; at: string } | null;
}
export interface AlertChannel {
  id: string; name: string; kind: "webhook" | "email"; enabled: boolean; config: { url?: string; recipients?: string[] };
  has_secret: boolean; violation_types: string[]; camera_ids: string[]; attach_evidence: boolean; created_at: string | null;
}
export interface AlertDelivery {
  id: string; channel_id: string; incident_id: string; status: "pending" | "sent" | "failed"; attempts: number;
  next_attempt_at: string; last_error: string | null; response_code: number | null; created_at: string | null;
  sent_at: string | null;
}
export interface AlertsInfo { email_available: boolean; webhook_allow_private: boolean; public_web_url: string | null;
  dispatcher: { sent: number; retried: number; failed: number } | null }
export interface AuditEntry {
  id: number; at: string; actor_id: string | null; actor_email: string | null; action: string; entity_type: string | null;
  entity_id: string | null; before: Record<string, unknown> | null; after: Record<string, unknown> | null; ip: string | null;
}
export interface ReportCamera {
  camera_id: string | null; camera_name: string; incidents: number; confirmed_by_review: number; discarded: number;
  compliant: number; possible: number; confirmed: number; unverifiable: number; person_frames: number; max_persons: number;
  compliance_pct: number | null;
}
export interface Report {
  title: string; period: string; start: string; end: string; generated_at: string; generated_by: string;
  cameras_filter: string[]; totals: { incidents: number; pending: number; confirmed_by_review: number; discarded: number };
  by_type: Record<string, number>; by_status: Record<string, number>; cameras: ReportCamera[];
  days: Array<{ day: string; incidents: number; compliant: number; possible: number; confirmed: number; unverifiable: number;
    compliance_pct: number | null }>;
  incidents: Array<{ id: string; confirmed_at: string; camera_name: string; violation_type: string; status: string;
    confidence: number; ended_at: string | null; end_reason: string | null }>;
  incidents_truncated: boolean; model_ids: string[]; compliance_pct: number | null; unverifiable_share_pct: number | null;
}
