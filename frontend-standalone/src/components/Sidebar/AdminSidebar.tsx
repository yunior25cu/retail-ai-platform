import {
  Avatar, Box, IconButton, List, ListItemButton, ListItemIcon,
  ListItemText, Tooltip, Typography,
} from "@mui/material";
import AdminPanelSettingsOutlinedIcon from "@mui/icons-material/AdminPanelSettingsOutlined";
import BusinessOutlinedIcon from "@mui/icons-material/BusinessOutlined";
import PeopleOutlineIcon from "@mui/icons-material/PeopleOutline";
import BarChartOutlinedIcon from "@mui/icons-material/BarChartOutlined";
import ArticleOutlinedIcon from "@mui/icons-material/ArticleOutlined";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import LogoutIcon from "@mui/icons-material/Logout";
import { useLocation, useNavigate } from "react-router-dom";
import { tokens } from "@/theme/tokens";
import { useAuth } from "@/hooks/useAuth";

/**
 * Sidebar for the super-admin panel. Distinct from the chat Sidebar:
 * - No conversation list
 * - No "Nueva conversación"
 * - No pins/metrics chat features
 * Items below mirror the v0.6.5-Nivel-2 spec: Tenants, Usuarios, Métricas
 * de plataforma, Logs, Configuración. Placeholders for sections that don't
 * have a real page yet ("Próximamente") so the IA navigation contract is
 * already documented in code.
 */

interface AdminNavItem {
  label: string;
  to: string;
  icon: React.ReactNode;
}

const ITEMS: AdminNavItem[] = [
  { label: "Tenants",               to: "/admin/tenants",  icon: <BusinessOutlinedIcon fontSize="small" /> },
  { label: "Usuarios",              to: "/admin/users",    icon: <PeopleOutlineIcon fontSize="small" /> },
  { label: "Métricas de plataforma", to: "/admin/metricas", icon: <BarChartOutlinedIcon fontSize="small" /> },
  { label: "Logs",                  to: "/admin/logs",     icon: <ArticleOutlinedIcon fontSize="small" /> },
  { label: "Configuración",         to: "/configuracion",  icon: <SettingsOutlinedIcon fontSize="small" /> },
];

const sx = {
  root: {
    width: tokens.sidebar.width, flexShrink: 0, display: "flex",
    flexDirection: "column", height: "100%",
    bgcolor: tokens.sidebar.bg, color: tokens.sidebar.text,
  },
  logo: { px: 2, py: 2, display: "flex", alignItems: "center", gap: 1 },
  item: (active: boolean) => ({
    mx: 0.75, my: 0.25, borderRadius: 1.5,
    bgcolor: active ? tokens.sidebar.active : "transparent",
    "&:hover": { bgcolor: tokens.sidebar.hover },
    color: tokens.sidebar.text,
  }),
  itemIcon: { minWidth: 32, color: "inherit" },
  footer: {
    mt: "auto", px: 1.5, py: 1.5,
    borderTop: `1px solid rgba(255,255,255,0.1)`,
  },
};

export function AdminSidebar() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout } = useAuth();

  const isActive = (to: string) =>
    location.pathname === to || location.pathname.startsWith(to + "/");

  return (
    <Box sx={sx.root}>
      {/* Logo */}
      <Box sx={sx.logo}>
        <AdminPanelSettingsOutlinedIcon sx={{ color: tokens.brand.primary, fontSize: 22 }} />
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="subtitle1" fontWeight={700} noWrap>
            Administración
          </Typography>
          <Typography variant="caption" sx={{ color: tokens.sidebar.textMuted }} noWrap>
            Plataforma
          </Typography>
        </Box>
      </Box>

      {/* Nav */}
      <List dense sx={{ flex: 1, overflowY: "auto", pt: 1 }}>
        {ITEMS.map((it) => (
          <ListItemButton
            key={it.to}
            selected={isActive(it.to)}
            onClick={() => navigate(it.to)}
            sx={sx.item(isActive(it.to))}
          >
            <ListItemIcon sx={sx.itemIcon}>{it.icon}</ListItemIcon>
            <ListItemText
              primary={it.label}
              primaryTypographyProps={{ fontSize: "0.85rem" }}
            />
          </ListItemButton>
        ))}
      </List>

      {/* Footer */}
      <Box sx={sx.footer}>
        <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 1 }}>
          <Avatar sx={{ width: 28, height: 28, bgcolor: tokens.brand.primary, fontSize: 12 }}>
            {user?.email?.[0]?.toUpperCase() ?? "?"}
          </Avatar>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography variant="caption" noWrap sx={{ display: "block", color: tokens.sidebar.text }}>
              {user?.email}
            </Typography>
            <Typography variant="caption" sx={{ color: tokens.sidebar.textMuted, fontSize: "0.65rem" }}>
              {user?.role}
            </Typography>
          </Box>
          <Tooltip title="Cerrar sesión">
            <IconButton size="small" sx={{ color: tokens.sidebar.textMuted }}
              onClick={() => { void logout(); }}>
              <LogoutIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Box>
      </Box>
    </Box>
  );
}
