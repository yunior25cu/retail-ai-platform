import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { CssBaseline, ThemeProvider, createTheme } from "@mui/material";
import { AuthProvider } from "@/store/auth.tsx";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { AppShell } from "@/components/Layout/AppShell";
import { Login } from "@/pages/Login";
import { Chat } from "@/pages/Chat";
import { NotFound } from "@/pages/NotFound";
import { ConfiguracionPage } from "@/pages/ConfiguracionPage";
import { AdminPage } from "@/pages/AdminPage";
import { tokens } from "@/theme/tokens";

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
            <Route
              path="/"
              element={
                <ProtectedRoute>
                  <Chat />
                </ProtectedRoute>
              }
            />
            <Route
              path="/configuracion"
              element={
                <ProtectedRoute requiredRoles={["super_admin", "superadmin", "admin_tenant", "direccion"]}>
                  <AppShell>
                    <ConfiguracionPage />
                  </AppShell>
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin"
              element={
                <ProtectedRoute requiredRoles={["super_admin", "superadmin"]}>
                  <AppShell>
                    <AdminPage />
                  </AppShell>
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
