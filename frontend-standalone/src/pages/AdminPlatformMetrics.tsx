import { Box, Card, CardContent, Typography } from "@mui/material";
import BarChartOutlinedIcon from "@mui/icons-material/BarChartOutlined";

/**
 * Placeholder for cross-tenant platform metrics. Listed in AdminSidebar so
 * the admin nav contract is complete; the real dashboard (active tenants,
 * total chats/month, cost vs budget, top tools across tenants) will land
 * in a follow-up sub-phase.
 */
export function AdminPlatformMetrics() {
  return (
    <Box sx={{ p: 4, maxWidth: 720, mx: "auto" }}>
      <Card variant="outlined" sx={{ textAlign: "center", py: 6 }}>
        <CardContent>
          <BarChartOutlinedIcon
            sx={{ fontSize: 56, color: "primary.light", mb: 2 }}
          />
          <Typography variant="h6" gutterBottom>
            Métricas de plataforma
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            Próximamente.
          </Typography>
          <Typography variant="caption" color="text.disabled">
            Vista cross-tenant: chats/mes, costo USD, top tools, alertas críticas.
          </Typography>
        </CardContent>
      </Card>
    </Box>
  );
}
