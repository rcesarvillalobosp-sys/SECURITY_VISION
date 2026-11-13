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

export async function refreshToken(): Promise<string | null> {
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const r = await fetch("/api/v1/auth/refresh", { method: "POST", credentials: "same-origin" });
        if (!r.ok) {
          setToken(null);
          return null;
        }
        const body = (await r.json()) as { access_token: string };
        setToken(body.access_token);
        return body.access_token;
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
