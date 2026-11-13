import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, ApiError, refreshToken, setToken, type Me } from "./api";

interface AuthState {
  me: Me | null;
  ready: boolean; // ya se intentó restaurar la sesión
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  can: (permission: string) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);
const REFRESH_EVERY_MS = 12 * 60 * 1000; // el token de acceso dura 15 min

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);

  const loadMe = useCallback(async () => setMe(await api.get<Me>("/api/v1/auth/me")), []);

  // Restaurar la sesión con la cookie de refresh (si existe) al cargar la página
  useEffect(() => {
    (async () => {
      try {
        if (await refreshToken()) await loadMe();
      } finally {
        setReady(true);
      }
    })();
  }, [loadMe]);

  // Renovación proactiva mientras hay sesión
  useEffect(() => {
    if (!me) return;
    const id = window.setInterval(async () => {
      if (!(await refreshToken())) setMe(null);
    }, REFRESH_EVERY_MS);
    return () => window.clearInterval(id);
  }, [me]);

  const login = useCallback(async (email: string, password: string) => {
    const r = await api.post<{ access_token: string }>("/api/v1/auth/login", { email, password });
    setToken(r.access_token);
    await loadMe();
  }, [loadMe]);

  const logout = useCallback(async () => {
    try {
      await api.post("/api/v1/auth/logout");
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
    }
    setToken(null);
    setMe(null);
  }, []);

  const can = useCallback((p: string) => !!me?.permissions.includes(p), [me]);

  return <AuthContext.Provider value={{ me, ready, login, logout, can }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth fuera de AuthProvider");
  return ctx;
}
