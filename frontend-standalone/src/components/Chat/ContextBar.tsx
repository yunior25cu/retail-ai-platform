import { Box, Chip, Typography } from "@mui/material";
import BusinessOutlinedIcon from "@mui/icons-material/BusinessOutlined";
import CalendarTodayOutlinedIcon from "@mui/icons-material/CalendarTodayOutlined";
import BadgeOutlinedIcon from "@mui/icons-material/BadgeOutlined";
import { tokens } from "@/theme/tokens";
import type { AuthUser } from "@/store/auth.tsx";

interface Props {
  user: AuthUser;
}

const ROLE_LABELS: Record<string, string> = {
  direccion:   "Dirección",
  produccion:  "Producción",
  compras:     "Compras",
  marca:       "Marca",
  tienda:      "Tienda",
  sku:         "Producto",
  admin_tenant:"Admin",
  superadmin:  "Superadmin",
  super_admin: "Superadmin",
};

function getPeriodLabel(role: string): string {
  const now = new Date();
  if (role === "direccion" || role === "admin_tenant" || role.includes("admin")) {
    return now.toLocaleDateString("es-UY", { month: "long", year: "numeric" });
  }
  // ISO week number
  const jan1 = new Date(now.getFullYear(), 0, 1);
  const week = Math.ceil(((now.getTime() - jan1.getTime()) / 86400000 + jan1.getDay() + 1) / 7);
  return `Semana ${week}`;
}

const chipSx = {
  height: 22,
  fontSize: "0.72rem",
  bgcolor: `${tokens.brand.primary}12`,
  color: tokens.brand.secondary,
  border: `1px solid ${tokens.brand.primary}30`,
  "& .MuiChip-icon": { fontSize: 12, color: tokens.brand.primary },
};

export function ContextBar({ user }: Props) {
  const roleLabel = ROLE_LABELS[user.role] ?? user.role;
  const period    = getPeriodLabel(user.role);
  const company   = `Tenant ${user.tenant_id}`;

  return (
    <Box
      sx={{
        display: "flex", alignItems: "center", gap: 0.75,
        px: 2, py: 0.75,
        borderBottom: "1px solid", borderColor: "grey.100",
        bgcolor: "#FAFBFC",
        flexWrap: "wrap",
      }}
    >
      <Typography variant="caption" color="text.disabled" sx={{ mr: 0.5, fontSize: "0.7rem" }}>
        Contexto:
      </Typography>
      <Chip icon={<BusinessOutlinedIcon />} label={company}  size="small" sx={chipSx} />
      <Chip icon={<CalendarTodayOutlinedIcon />} label={period} size="small" sx={chipSx} />
      <Chip icon={<BadgeOutlinedIcon />} label={roleLabel}   size="small" sx={chipSx} />
    </Box>
  );
}
