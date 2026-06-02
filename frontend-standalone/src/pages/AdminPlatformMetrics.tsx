import { useEffect, useState } from "react";
import {
  Alert, Box, Card, CardContent, Chip, CircularProgress, Paper,
  Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  Typography,
} from "@mui/material";
import BarChartOutlinedIcon from "@mui/icons-material/BarChartOutlined";
import BusinessOutlinedIcon from "@mui/icons-material/BusinessOutlined";
import { api, type PlatformMetricsResponse } from "@/api/client";
import { tokens } from "@/theme/tokens";

function formatCurrency(n: number): string {
  return `$${n.toFixed(2)}`;
}

function formatPeriod(period: string): string {
  const [y, m] = period.split("-").map(Number);
  if (!y || !m) return period;
  return new Intl.DateTimeFormat("es", { month: "long", year: "numeric" })
    .format(new Date(y, m - 1, 1))
    .replace(/^./, (c) => c.toUpperCase());
}

function KpiCell({ value, label }: { value: string; label: string }) {
  return (
    <Card variant="outlined" sx={{ flex: 1, textAlign: "center" }}>
      <CardContent sx={{ py: 2 }}>
        <Typography variant="h5" sx={{ fontWeight: 700 }}>{value}</Typography>
        <Typography variant="caption" color="text.secondary">{label}</Typography>
      </CardContent>
    </Card>
  );
}

export function AdminPlatformMetrics() {
  const [data, setData] = useState<PlatformMetricsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .adminGetPlatformMetrics()
      .then((d) => setData(d))
      .catch((e) => setError(e?.response?.data?.detail ?? "Error al cargar métricas"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", py: 8 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error || !data) {
    return (
      <Box sx={{ p: 4, maxWidth: 720, mx: "auto" }}>
        <Alert severity="error">{error ?? "No se pudieron cargar las métricas."}</Alert>
      </Box>
    );
  }

  return (
    <Box sx={{ p: 4, maxWidth: 960, mx: "auto" }}>
      <Stack direction="row" alignItems="center" spacing={1.5} sx={{ mb: 3 }}>
        <BarChartOutlinedIcon sx={{ color: tokens.brand.primary, fontSize: 28 }} />
        <Box>
          <Typography variant="h5" fontWeight={700}>Métricas de plataforma</Typography>
          <Typography variant="body2" color="text.secondary">
            {formatPeriod(data.period)} · uso agregado de todos los tenants
          </Typography>
        </Box>
      </Stack>

      {/* KPIs */}
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ mb: 3 }}>
        <KpiCell value={String(data.total_chats)}             label="Chats" />
        <KpiCell value={formatCurrency(data.total_cost_usd)}  label="Costo USD" />
        <KpiCell value={String(data.active_tenants)}          label="Tenants activos" />
        <KpiCell
          value={data.top_tool || "—"}
          label={data.top_tool ? `Top tool (${data.top_tool_count} usos)` : "Sin tools"}
        />
      </Stack>

      {/* Per-tenant breakdown */}
      <Typography variant="subtitle1" sx={{ mb: 1, fontWeight: 600 }}>
        Por tenant
      </Typography>
      {data.by_tenant.length === 0 ? (
        <Alert severity="info">
          Sin actividad este mes. Cuando algún tenant chatee, aparecerán aquí
          sus chats y costo.
        </Alert>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell sx={{ fontWeight: 600 }}>Tenant</TableCell>
                <TableCell align="right" sx={{ fontWeight: 600 }}>Chats</TableCell>
                <TableCell align="right" sx={{ fontWeight: 600 }}>Costo USD</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {data.by_tenant.map((row) => (
                <TableRow key={row.tenant_id} hover>
                  <TableCell>
                    <Stack direction="row" spacing={1} alignItems="center">
                      <BusinessOutlinedIcon sx={{ fontSize: 16, color: "text.disabled" }} />
                      <Typography variant="body2">{row.tenant_name}</Typography>
                      <Chip
                        label={`id ${row.tenant_id}`}
                        size="small"
                        variant="outlined"
                        sx={{ height: 18, fontSize: "0.65rem" }}
                      />
                    </Stack>
                  </TableCell>
                  <TableCell align="right">{row.chats}</TableCell>
                  <TableCell align="right">{formatCurrency(row.cost_usd)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Box>
  );
}
