/**
 * Cliente WHEP (RFC 9725) contra MediaMTX.
 *
 * Se envía la oferta con los candidatos ya recogidos (espera máx. 2 s). En la Fase 9 se probó *trickle
 * ICE* (enviar la oferta al instante y los candidatos después por PATCH): en 15 + 15 mediciones fue más
 * LENTO (mediana 1,79 s frente a 1,26 s hasta el primer fotograma), porque añade una ida y vuelta y aquí la
 * recolección local es casi instantánea. El arranque lo domina la espera al siguiente fotograma clave.
 *
 * Al cerrar se borra la sesión en el servidor (DELETE a la URL de ``Location``) para liberarla al momento.
 *
 * Autorización (Fase 10): se envía el token de acceso de la web (``Authorization: Bearer``). MediaMTX lo
 * reenvía a la API, que solo permite leer cámaras existentes a usuarios con ``cameras:read``.
 */
import { getToken } from "./api";

function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const t = getToken();
  return t ? { ...extra, Authorization: `Bearer ${t}` } : extra;
}

export interface WhepSession { pc: RTCPeerConnection; close: () => void; startedAt: number }

export async function startWhep(url: string, video: HTMLVideoElement, gatherTimeoutMs = 2000): Promise<WhepSession> {
  const startedAt = performance.now();
  const pc = new RTCPeerConnection();
  pc.addTransceiver("video", { direction: "recvonly" });
  pc.ontrack = (e) => {
    video.srcObject = e.streams[0] ?? new MediaStream([e.track]);
  };
  await pc.setLocalDescription(await pc.createOffer());
  await new Promise<void>((resolve) => {
    if (pc.iceGatheringState === "complete") return resolve();
    const t = window.setTimeout(resolve, gatherTimeoutMs);
    pc.addEventListener("icegatheringstatechange", () => {
      if (pc.iceGatheringState === "complete") {
        window.clearTimeout(t);
        resolve();
      }
    });
  });
  const r = await fetch(url, { method: "POST", headers: authHeaders({ "Content-Type": "application/sdp" }),
    body: pc.localDescription!.sdp });
  if (!r.ok) {
    pc.close();
    throw new Error(`WHEP ${r.status}`);
  }
  const loc = r.headers.get("Location");
  const session = loc ? new URL(loc, url).toString() : null;
  await pc.setRemoteDescription({ type: "answer", sdp: await r.text() });
  const close = () => {
    pc.close();
    if (session) void fetch(session, { method: "DELETE", headers: authHeaders() }).catch(() => undefined);
  };
  return { pc, close, startedAt };
}
