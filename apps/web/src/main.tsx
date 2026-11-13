import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/600.css";
import "./index.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";
import { Shell } from "./components/Shell";
import { ApiError } from "./lib/api";
import { AuthProvider, useAuth } from "./lib/auth";
import { Dashboard } from "./pages/Dashboard";
import { IncidentDetail, Incidents } from "./pages/Incidents";
import { Login } from "./pages/Login";
import { Monitor } from "./pages/Monitor";
import { Account } from "./pages/Account";
import { Reports } from "./pages/Reports";
import { AlertsAdmin } from "./pages/admin/Alerts";
import { AuditLog } from "./pages/admin/Audit";
import { CamerasAdmin } from "./pages/admin/Cameras";
import { ModelsAdmin } from "./pages/admin/Models";
import { ProfilesAdmin } from "./pages/admin/Profiles";
import { UsersAdmin } from "./pages/admin/Users";
import { ZoneEditor } from "./pages/admin/ZoneEditor";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (n, e) => !(e instanceof ApiError && [401, 403, 404].includes(e.status)) && n < 2,
      refetchOnWindowFocus: false,
    },
  },
});

function App() {
  const { me, ready } = useAuth();
  if (!ready) return <div className="grid h-full place-items-center text-sm text-ink-400">Cargando…</div>;
  if (!me) return <Login />;
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/monitor" element={<Monitor />} />
        <Route path="/incidents" element={<Incidents />} />
        <Route path="/incidents/:id" element={<IncidentDetail />} />
        <Route path="/reports" element={<Reports />} />
        <Route path="/account" element={<Account />} />
        <Route path="/admin/cameras" element={<CamerasAdmin />} />
        <Route path="/admin/cameras/:id/zones" element={<ZoneEditor />} />
        <Route path="/admin/profiles" element={<ProfilesAdmin />} />
        <Route path="/admin/models" element={<ModelsAdmin />} />
        <Route path="/admin/alerts" element={<AlertsAdmin />} />
        <Route path="/admin/users" element={<UsersAdmin />} />
        <Route path="/admin/audit" element={<AuditLog />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
);
