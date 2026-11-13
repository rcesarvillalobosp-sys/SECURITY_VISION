import { useEffect, useRef, useState } from "react";
import { request, type Camera } from "../lib/api";
import { CAMERA_STATUS_LABEL, containRect, MISSING_LABEL, STATUS_COLOR, STATUS_LABEL } from "../lib/format";
import { useLiveFrame, type LiveFrame } from "../lib/live";
import { CamDot } from "./ui";

/** WHEP (WebRTC-HTTP Egress Protocol) contra MediaMTX: vídeo en directo de baja latencia. */
async function startWhep(url: string, video: HTMLVideoElement): Promise<RTCPeerConnection> {
  const pc = new RTCPeerConnection();
  pc.addTransceiver("video", { direction: "recvonly" });
  pc.ontrack = (e) => {
    video.srcObject = e.streams[0] ?? new MediaStream([e.track]);
  };
  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  await new Promise<void>((resolve) => {
    if (pc.iceGatheringState === "complete") return resolve();
    const t = window.setTimeout(resolve, 2000);
    pc.addEventListener("icegatheringstatechange", () => {
      if (pc.iceGatheringState === "complete") {
        window.clearTimeout(t);
        resolve();
      }
    });
  });
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/sdp" },
    body: pc.localDescription!.sdp });
  if (!r.ok) {
    pc.close();
    throw new Error(`WHEP ${r.status}`);
  }
  await pc.setRemoteDescription({ type: "answer", sdp: await r.text() });
  return pc;
}

type Mode = "webrtc" | "snapshot" | "none";

function useVideo(camera: Camera, video: React.RefObject<HTMLVideoElement | null>) {
  const [mode, setMode] = useState<Mode>("none");
  const [snapshot, setSnapshot] = useState<string | null>(null);
  useEffect(() => {
    let pc: RTCPeerConnection | null = null;
    let cancelled = false;
    let timer: number | undefined;
    let url: string | null = null;
    const pollSnapshot = async () => {
      try {
        const blob = await request<Blob>(`/api/v1/cameras/${camera.id}/snapshot`);
        if (cancelled) return;
        if (url) URL.revokeObjectURL(url);
        url = URL.createObjectURL(blob);
        setSnapshot(url);
        setMode("snapshot");
      } catch {
        if (!cancelled) setMode((m) => (m === "webrtc" ? m : "none"));
      }
      if (!cancelled) timer = window.setTimeout(pollSnapshot, 1500);
    };
    (async () => {
      if (camera.webrtc_url && video.current) {
        try {
          pc = await startWhep(camera.webrtc_url, video.current);
          if (cancelled) return pc.close();
          setMode("webrtc");
          pc.onconnectionstatechange = () => {
            if (pc && ["failed", "disconnected", "closed"].includes(pc.connectionState) && !cancelled) {
              setMode("none");
              void pollSnapshot();
            }
          };
          return;
        } catch {
          /* sin WebRTC (MediaMTX caído, red): se usa el snapshot */
        }
      }
      void pollSnapshot();
    })();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      pc?.close();
      if (url) URL.revokeObjectURL(url);
    };
  }, [camera.id, camera.webrtc_url, video]);
  return { mode, snapshot };
}

function drawOverlay(canvas: HTMLCanvasElement, frame: LiveFrame | null, showItems: boolean) {
  const dpr = window.devicePixelRatio || 1;
  const { clientWidth: cw, clientHeight: ch } = canvas;
  if (canvas.width !== cw * dpr || canvas.height !== ch * dpr) {
    canvas.width = cw * dpr;
    canvas.height = ch * dpr;
  }
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cw, ch);
  if (!frame) return;
  const r = containRect(cw, ch, frame.w, frame.h);
  const X = (v: number) => r.x + v * r.w;
  const Y = (v: number) => r.y + v * r.h;
  ctx.font = "600 11px 'IBM Plex Mono', monospace";
  for (const t of frame.tracks) {
    const color = STATUS_COLOR[t.s ?? "NO_VERIFICABLE"] ?? "#8a94a3";
    const [x1, y1, x2, y2] = t.b;
    ctx.strokeStyle = color;
    ctx.lineWidth = t.s === "INCUMPLIMIENTO_CONFIRMADO" ? 3 : 2;
    ctx.strokeRect(X(x1), Y(y1), X(x2) - X(x1), Y(y2) - Y(y1));
    const label = `P${t.id}`;
    const w = ctx.measureText(label).width + 8;
    ctx.fillStyle = color;
    ctx.fillRect(X(x1), Y(y1) - 15, w, 15);
    ctx.fillStyle = "#070a0e";
    ctx.fillText(label, X(x1) + 4, Y(y1) - 4);
  }
  if (!showItems) return;
  for (const it of frame.items) {
    const [x1, y1, x2, y2] = it.b;
    ctx.strokeStyle = it.p == null ? "rgba(255,255,255,0.6)" : it.c.startsWith("no_") ? "#ff3b3b" : "#2bd17e";
    ctx.lineWidth = 1.25;
    ctx.setLineDash(it.a ? [3, 3] : []);
    ctx.strokeRect(X(x1), Y(y1), X(x2) - X(x1), Y(y2) - Y(y1));
  }
  ctx.setLineDash([]);
}

export function CameraTile({ camera, focused = false, onFocus }:
  { camera: Camera; focused?: boolean; onFocus?: () => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const frame = useLiveFrame(camera.id);
  const { mode, snapshot } = useVideo(camera, video);
  const [showItems, setShowItems] = useState(true);
  const fresh = frame && Date.now() - new Date(frame.ts).getTime() < 5000;

  useEffect(() => {
    if (canvas.current) drawOverlay(canvas.current, fresh ? frame : null, showItems);
  }, [frame, fresh, showItems]);
  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const ro = new ResizeObserver(() => drawOverlay(el, fresh ? frame : null, showItems));
    ro.observe(el);
    return () => ro.disconnect();
  }, [frame, fresh, showItems]);

  const counts: Record<string, number> = {};
  for (const t of fresh ? frame!.tracks : []) counts[t.s ?? "NO_VERIFICABLE"] = (counts[t.s ?? "NO_VERIFICABLE"] ?? 0) + 1;
  const alert = (counts.INCUMPLIMIENTO_CONFIRMADO ?? 0) > 0;

  return (
    <article className={`panel flex min-w-0 flex-col overflow-hidden ${alert ? "border-alert/70" : ""}`}>
      <header className="flex items-center gap-2 border-b border-ink-700 px-3 py-1.5">
        <CamDot status={camera.status} />
        <button onClick={onFocus} className="truncate text-left text-sm font-medium hover:text-signal">{camera.name}</button>
        <span className="text-[11px] text-ink-400">{CAMERA_STATUS_LABEL[camera.status ?? ""] ?? camera.status ?? "—"}</span>
        <span className="ml-auto flex items-center gap-2">
          <span className="rounded bg-ink-800 px-1.5 py-0.5 text-[10px] tracking-wide text-ink-400 uppercase">
            {mode === "webrtc" ? "WebRTC" : mode === "snapshot" ? "Snapshot" : "Sin vídeo"}
          </span>
          <label className="flex cursor-pointer items-center gap-1 text-[11px] text-ink-400">
            <input type="checkbox" checked={showItems} onChange={(e) => setShowItems(e.target.checked)}
              className="accent-[var(--color-signal)]" />EPP
          </label>
        </span>
      </header>
      <div className={`relative bg-ink-950 ${focused ? "aspect-video" : "aspect-video"}`}>
        <video ref={video} autoPlay muted playsInline
          className={`absolute inset-0 size-full object-contain ${mode === "webrtc" ? "" : "hidden"}`} />
        {mode === "snapshot" && snapshot && (
          <img src={snapshot} alt={`Imagen de ${camera.name}`} className="absolute inset-0 size-full object-contain" />
        )}
        {mode === "none" && (
          <div className="absolute inset-0 grid place-items-center text-sm text-ink-400">
            {camera.enabled ? "Esperando imagen…" : "Cámara deshabilitada"}
          </div>
        )}
        <canvas ref={canvas} className="pointer-events-none absolute inset-0 size-full" />
      </div>
      <footer className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-ink-700 px-3 py-1.5 text-[11px]">
        <span className="num text-ink-300">{fresh ? frame!.tracks.length : 0} personas</span>
        {Object.entries(counts).map(([s, n]) => (
          <span key={s} className="num" style={{ color: STATUS_COLOR[s] }} title={STATUS_LABEL[s]}>● {n}</span>
        ))}
        {fresh && frame!.tracks.filter((t) => t.s === "INCUMPLIMIENTO_CONFIRMADO" || t.s === "POSIBLE_INCUMPLIMIENTO")
          .slice(0, 2).map((t) => (
            <span key={t.id} className="text-possible">
              P{t.id}: {Object.entries(t.ppe).filter(([, v]) => v === "missing").map(([k]) => MISSING_LABEL[k] ?? k).join(", ") || "revisar"}
            </span>
          ))}
        {!fresh && <span className="text-ink-400">sin análisis reciente</span>}
      </footer>
    </article>
  );
}
