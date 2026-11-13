export const PPE_LABEL: Record<string, string> = {
  person: "Persona",
  helmet: "Casco",
  no_helmet: "Sin casco",
  safety_vest: "Chaleco",
  no_vest: "Sin chaleco",
  safety_boot: "Botas",
  no_safety_boot: "Sin botas",
  gloves: "Guantes",
  no_gloves: "Sin guantes",
  goggles: "Gafas",
  no_goggles: "Sin gafas",
};

export const STATUS_LABEL: Record<string, string> = {
  CUMPLIMIENTO: "Cumplimiento",
  EN_REVISION: "En revisión",
  POSIBLE_INCUMPLIMIENTO: "Posible incumplimiento",
  INCUMPLIMIENTO_CONFIRMADO: "Incumplimiento confirmado",
  NO_VERIFICABLE: "No verificable",
};

/** Mismo código de color en vídeo, tablas y gráficas. */
export const STATUS_COLOR: Record<string, string> = {
  CUMPLIMIENTO: "#2bd17e",
  EN_REVISION: "#f2c94c",
  POSIBLE_INCUMPLIMIENTO: "#ff8c1a",
  INCUMPLIMIENTO_CONFIRMADO: "#ff3b3b",
  NO_VERIFICABLE: "#8a94a3",
};

export const INCIDENT_STATUS_LABEL: Record<string, string> = {
  PENDIENTE: "Pendiente",
  EN_REVISION: "En revisión",
  CONFIRMADO: "Confirmado",
  DESCARTADO: "Descartado",
  RESUELTO: "Resuelto",
};

export const CAMERA_STATUS_LABEL: Record<string, string> = {
  streaming: "En línea",
  connecting: "Conectando",
  reconnecting: "Reconectando",
  stalled: "Sin imagen",
  stopped: "Detenida",
};

export const fmtDateTime = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString("es-ES", { dateStyle: "short", timeStyle: "medium" }) : "—";
export const fmtTime = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";
export const pct = (v: number | null | undefined) => (v == null ? "—" : `${v.toFixed(1)} %`);

export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return `hace ${s} s`;
  if (s < 3600) return `hace ${Math.round(s / 60)} min`;
  if (s < 86400) return `hace ${Math.round(s / 3600)} h`;
  return `hace ${Math.round(s / 86400)} d`;
}

/** Rectángulo que ocupa una imagen/vídeo con object-fit: contain dentro de su contenedor. */
export function containRect(boxW: number, boxH: number, srcW: number, srcH: number) {
  if (!srcW || !srcH || !boxW || !boxH) return { x: 0, y: 0, w: boxW, h: boxH };
  const s = Math.min(boxW / srcW, boxH / srcH);
  const w = srcW * s;
  const h = srcH * s;
  return { x: (boxW - w) / 2, y: (boxH - h) / 2, w, h };
}

/** Etiqueta del EPP que FALTA (las clases "no_*" no siguen el patrón no_<clase>). */
export const MISSING_LABEL: Record<string, string> = {
  helmet: "Sin casco",
  safety_vest: "Sin chaleco",
  safety_boot: "Sin botas",
  gloves: "Sin guantes",
  goggles: "Sin gafas",
};
