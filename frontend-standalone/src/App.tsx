import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { CssBaseline, ThemeProvider, createTheme } from "@mui/material";
import { AuthProvider } from "@/store/auth.tsx";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { AppShell } from "@/components/Layout/AppShell";
import { AdminShell } from "@/components/Layout/AdminShell";
import { Login } from "@/pages/Login";
import { Chat } from "@/pages/Chat";
import { NotFound } from "@/pages/NotFound";
import { ConfiguracionPage } from "@/pages/ConfiguracionPage";
import { AdminPage } from "@/pages/AdminPage";
import { AdminPlatformMetrics } from "@/pages/AdminPlatformMetrics";
import { AdminLogs } from "@/pages/AdminLogs";
import { tokens } from "@/theme/tokens";

const SUPERADMIN_ROLES = ["super_admin", "superadmin"];

const theme = createTheme({
  palette: {
    primary:   { main: tokens.brand.primary },
    secondary: { main: tokens.brand.secondary },
  },
  typography: {
    fontFamily: '"Inter", "Roboto", "Helvetica", "Arial", sans-serif',
  },
  components: {
    MuiButton: {
      styleOverrides: { root: { textTransform: "none", borderRadius: 8 } },
    },
    MuiCard: {
      styleOverrides: { root: { borderRadius: 12 } },
    },
  },
});

export default function App() {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<Login />} />

            {/* Chat home — super-admins are bounced to /admin (no business
                role, no tenant context). */}
            <Route
              path="/"
              element={
                <ProtectedRoute blockSuperadmin>
                  <Chat />
                </ProtectedRoute>
              }
            />

            {/* Configuración — shared between tenant admins and super-admins
                (kept here so it works under either shell). */}
            <Route
              path="/configuracion"
              element={
                <ProtectedRoute requiredRoles={[...SUPERADMIN_ROLES, "admin_tenant", "direccion"]}>
                  <AppShell>
                    <ConfiguracionPage />
                  </AppShell>
                </ProtectedRoute>
              }
            />

            {/* Admin section — only super-admins; all routes share AdminShell. */}
            <Route
              path="/admin"
              element={
                <ProtectedRoute requiredRoles={SUPERADMIN_ROLES}>
                  <AdminShell>
                    <AdminPage initialTab="tenants" />
                  </AdminShell>
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin/tenants"
              element={
                <ProtectedRoute requiredRoles={SUPERADMIN_ROLES}>
                  <AdminShell>
                    <AdminPage initialTab="tenants" />
                  </AdminShell>
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin/users"
              element={
                <ProtectedRoute requiredRoles={SUPERADMIN_ROLES}>
                  <AdminShell>
                    <AdminPage initialTab="users" />
                  </AdminShell>
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin/metricas"
              element={
                <ProtectedRoute requiredRoles={SUPERADMIN_ROLES}>
                  <AdminShell>
                    <AdminPlatformMetrics />
                  </AdminShell>
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin/logs"
              element={
                <ProtectedRoute requiredRoles={SUPERADMIN_ROLES}>
                  <AdminShell>
                    <AdminLogs />
                  </AdminShell>
                </ProtectedRoute>
              }
            />

            <Route path="/404" element={<NotFound />} />
            <Route path="*" element={<Navigate to="/404" replace />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </ThemeProvider>
  );
}
