import { Box, Card, CardContent, Typography } from "@mui/material";
import ArticleOutlinedIcon from "@mui/icons-material/ArticleOutlined";

/**
 * Placeholder for cross-tenant audit logs. Real implementation will tail
 * audit.conversation_log (PG) + api_audit.ai_audit_log (SS) with filters
 * by tenant / user / status / date range. Listed in AdminSidebar so the
 * nav contract is documented; backend already persists everything needed.
 */
export function AdminLogs() {
  return (
    <Box sx={{ p: 4, maxWidth: 720, mx: "auto" }}>
      <Card variant="outlined" sx={{ textAlign: "center", py: 6 }}>
        <CardContent>
          <ArticleOutlinedIcon
            sx={{ fontSize: 56, color: "primary.light", mb: 2 }}
          />
          <Typography variant="h6" gutterBottom>
            Logs
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            Próximamente.
          </Typography>
          <Typography variant="caption" color="text.disabled">
            Audit trail cross-tenant: requests, errores, tokens, costo, tools invocadas.
          </Typography>
        </CardContent>
      </Card>
    </Box>
  );
}
