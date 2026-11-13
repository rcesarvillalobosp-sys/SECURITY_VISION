import { afterEach, describe, expect, it, vi } from "vitest";
import { api, getToken, setToken } from "./api";
import { containRect } from "./format";

describe("containRect (superposición sobre vídeo con object-fit: contain)", () => {
  it("bandas laterales cuando el contenedor es más ancho", () => {
    expect(containRect(1600, 600, 1280, 720)).toEqual({ x: (1600 - 1066.6666666666667) / 2, y: 0, w: 1066.6666666666667, h: 600 });
  });
  it("bandas superior/inferior cuando el contenedor es más alto", () => {
    const r = containRect(640, 640, 1280, 720);
    expect(r.w).toBe(640);
    expect(r.h).toBe(360);
    expect(r.y).toBe(140);
  });
  it("tamaño de fuente desconocido: ocupa todo", () => {
    expect(containRect(100, 50, 0, 0)).toEqual({ x: 0, y: 0, w: 100, h: 50 });
  });
});

describe("cliente de API", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    setToken(null);
  });

  it("ante 401 renueva el token UNA vez (aunque haya peticiones simultáneas) y reintenta", async () => {
    setToken("viejo");
    let refreshes = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/v1/auth/refresh") {
        refreshes++;
        return new Response(JSON.stringify({ access_token: "nuevo" }), { status: 200, headers: { "content-type": "application/json" } });
      }
      const auth = new Headers(init?.headers).get("Authorization");
      if (auth === "Bearer viejo") return new Response("{}", { status: 401 });
      return new Response(JSON.stringify({ ok: true }), { status: 200, headers: { "content-type": "application/json" } });
    }));
    const [a, b] = await Promise.all([api.get<{ ok: boolean }>("/api/v1/x"), api.get<{ ok: boolean }>("/api/v1/y")]);
    expect(a.ok && b.ok).toBe(true);
    expect(refreshes).toBe(1);
    expect(getToken()).toBe("nuevo");
  });

  it("si la renovación falla, borra el token y propaga el error", async () => {
    setToken("viejo");
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "sesión inválida" }), { status: 401,
      headers: { "content-type": "application/json" } })));
    await expect(api.get("/api/v1/x")).rejects.toThrow("sesión inválida");
    expect(getToken()).toBeNull();
  });
});
