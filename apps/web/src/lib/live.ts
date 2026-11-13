/**
 * Conexión WebSocket con la API: fotogramas analizados (cajas, IDs, estados) y eventos.
 * Reconecta con backoff exponencial y renueva la autenticación cuando cambia el token.
 */
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { getToken, onTokenChange } from "./api";

export interface LiveTrack { id: number; b: [number, number, number, number]; s: string | null; ppe: Record<string, string> }
export interface LiveItem { c: string; b: [number, number, number, number]; p: number | null; a: boolean }
export interface LiveFrame { cam: string; ts: string; fid: number; w: number; h: number; tracks: LiveTrack[]; items: LiveItem[] }
export interface LiveEvent { event: string; data: Record<string, unknown>; receivedAt: number }

type ConnState = "connecting" | "open" | "closed";

class LiveClient {
  frames = new Map<string, LiveFrame>();
  events: LiveEvent[] = [];
  state: ConnState = "closed";
  private ws: WebSocket | null = null;
  private subs = new Map<string, number>(); // cámara -> nº de componentes suscritos
  private listeners = new Set<() => void>();
  private eventListeners = new Set<(e: LiveEvent) => void>();
  private retry = 0;
  private stopped = true;
  private version = 0;

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    this.connect();
    onTokenChange((t) => {
      if (t && this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ type: "auth", token: t }));
    });
  }

  stop(): void {
    this.stopped = true;
    this.ws?.close();
  }

  private connect(): void {
    const token = getToken();
    if (!token || this.stopped) {
      window.setTimeout(() => this.connect(), 1000);
      return;
    }
    this.setState("connecting");
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/api/v1/ws`);
    this.ws = ws;
    ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token: getToken() }));
    ws.onmessage = (m) => {
      const msg = JSON.parse(m.data as string);
      if (msg.type === "ready") {
        this.retry = 0;
        this.setState("open");
        this.sendSubscription();
      } else if (msg.type === "frame") {
        this.frames.set(msg.data.cam, msg.data);
        this.emit();
      } else if (msg.type === "event") {
        const e: LiveEvent = { event: msg.event, data: msg.data, receivedAt: Date.now() };
        this.events = [e, ...this.events].slice(0, 100);
        this.eventListeners.forEach((l) => l(e));
        this.emit();
      }
    };
    ws.onclose = () => {
      this.setState("closed");
      if (this.stopped) return;
      const delay = Math.min(30000, 1000 * 2 ** this.retry++);
      window.setTimeout(() => this.connect(), delay);
    };
  }

  private sendSubscription(): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "subscribe", cameras: [...this.subs.keys()] }));
    }
  }

  subscribe(cam: string): () => void {
    this.subs.set(cam, (this.subs.get(cam) ?? 0) + 1);
    this.sendSubscription();
    return () => {
      const n = (this.subs.get(cam) ?? 1) - 1;
      if (n <= 0) this.subs.delete(cam);
      else this.subs.set(cam, n);
      this.sendSubscription();
    };
  }

  onEvent(l: (e: LiveEvent) => void): () => void {
    this.eventListeners.add(l);
    return () => this.eventListeners.delete(l);
  }

  listen(l: () => void): () => void {
    this.listeners.add(l);
    return () => this.listeners.delete(l);
  }

  snapshot(): number {
    return this.version;
  }

  private setState(s: ConnState): void {
    this.state = s;
    this.emit();
  }

  private emit(): void {
    this.version++;
    this.listeners.forEach((l) => l());
  }
}

export const live = new LiveClient();

/** Re-render en cada mensaje: usar solo en componentes pequeños o con memo. */
export function useLiveVersion(): number {
  return useSyncExternalStore((l) => live.listen(l), () => live.snapshot());
}

export function useLiveFrame(cam: string | null): LiveFrame | null {
  const [frame, setFrame] = useState<LiveFrame | null>(null);
  const last = useRef<string>("");
  useEffect(() => {
    if (!cam) return;
    const unsub = live.subscribe(cam);
    const unlisten = live.listen(() => {
      const f = live.frames.get(cam);
      const key = f ? `${f.fid}|${f.ts}` : "";
      if (f && key !== last.current) {
        last.current = key;
        setFrame(f);
      }
    });
    return () => {
      unsub();
      unlisten();
    };
  }, [cam]);
  return frame;
}
