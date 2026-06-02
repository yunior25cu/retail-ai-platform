import { Navigate, useLocation } from "react-router-dom";
import { Box, CircularProgress } from "@mui/material";
import { useAuth } from "@/hooks/useAuth";

interface Props {
  children: React.ReactNode;
  requiredRoles?: string[];
  /**
   * If true, super-admins entering this route are bounced to /admin.
   * Used on the chat route so the super-admin home is the admin panel,
   * not the operational chat (which would have no tenant context anyway).
   */
  blockSuperadmin?: boolean;
}

const SUPERADMIN_ROLES = new Set(["super_admin", "superadmin"]);

export function ProtectedRoute({ children, requiredRoles, blockSuperadmin }: Props) {
  const { isAuthenticated, loading, user } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <Box sx={{ height: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <CircularProgress />
      </Box>
    );
  }

  if (!isAuthenticated) return <Navigate to="/login" replace />;

  // Super-admin landing on a chat route → push to the admin panel.
  // Anti-loop: only bounce if we are NOT already going to /admin.
  if (blockSuperadmin && user && SUPERADMIN_ROLES.has(user.role)
      && !location.pathname.startsWith("/admin")) {
    return <Navigate to="/admin" replace />;
  }

  if (requiredRoles && user && !requiredRoles.includes(user.role)) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
}
