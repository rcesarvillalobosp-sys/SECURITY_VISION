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

/** Umbrales del motor de reglas: etiqueta y ayuda para el editor de perfiles. */
export const THRESHOLD_INFO: Record<string, { label: string; help: string; step?: number }> = {
  window_seconds: { label: "Ventana (s)", help: "Observaciones recientes que se tienen en cuenta", step: 0.5 },
  min_observations: { label: "Observaciones mínimas", help: "Verificables en la ventana para decidir" },
  min_verifiable_ratio: { label: "Fracción verificable mín.", help: "Por debajo: no verificable", step: 0.05 },
  present_ratio: { label: "Cuota de presencia", help: "Para considerar el EPP presente", step: 0.05 },
  absent_ratio: { label: "Cuota de ausencia", help: "Para considerar el EPP ausente", step: 0.05 },
  implicit_absent_weight: { label: "Peso ausencia implícita", help: "No ver el EPP frente a detectar 'sin EPP'", step: 0.05 },
  require_explicit_negative: { label: "Exigir detección 'sin EPP'", help: "Ausente solo con detección explícita" },
  confirm_seconds: { label: "Confirmar tras (s)", help: "Ausencia sostenida antes de confirmar", step: 0.5 },
  min_absent_observations: { label: "Ausencias mínimas", help: "Para confirmar un incumplimiento" },
  min_explicit_absences_to_confirm: { label: "Detecciones 'sin EPP' mín.", help: "Evidencia positiva de ausencia para confirmar" },
  clear_seconds: { label: "Cerrar tras (s)", help: "EPP visto de nuevo de forma sostenida", step: 0.5 },
  cooldown_seconds: { label: "Enfriamiento (s)", help: "No re-confirmar la misma persona y EPP antes de", step: 5 },
  forget_seconds: { label: "Olvidar tras (s)", help: "Persona que deja de aparecer", step: 1 },
  min_person_height_px: { label: "Altura mín. persona (px)", help: "Más pequeñas: no verificables" },
  min_region_px: { label: "Región mín. (px)", help: "Región corporal más pequeña: no verificable" },
  border_margin: { label: "Margen de borde", help: "Caja que toca el borde: región cortada", step: 0.005 },
  occlusion_ioa: { label: "Oclusión (IoA)", help: "Región tapada por otra persona", step: 0.05 },
  min_person_confidence: { label: "Confianza mín. persona", help: "Detección de persona poco segura", step: 0.05 },
  min_item_confidence: { label: "Confianza mín. EPP", help: "EPP con menos confianza no cuenta", step: 0.05 },
};

export const ROLE_LABEL: Record<string, string> = {
  admin: "Administrador", supervisor: "Supervisor", operator: "Operador", viewer: "Solo lectura",
};

export const SOURCE_LABEL: Record<string, string> = { rtsp: "RTSP / IP", usb: "USB", file: "Archivo", test: "Patrón de prueba" };
