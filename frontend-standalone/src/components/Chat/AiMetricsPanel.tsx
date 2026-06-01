import { useEffect, useState } from "react";
import {
  Box, CircularProgress, Divider, LinearProgress, Typography,
} from "@mui/material";
import QueryStatsOutlinedIcon from "@mui/icons-material/QueryStatsOutlined";
import { api, type MetricsResponse } from "@/api/client";
import { tokens } from "@/theme/tokens";

const ROLE_LABELS: Record<string, string> = {
  direccion:  "Dirección",
  produccion: "Producción",
  compras:    "Compras",
  marca:      "Marca",
  tienda:     "Tienda",
  sku:        "Producto",
};

function KpiCard({ label, value }: { label: string; value: string | number }) {
  return (
    <Box
      sx={{
        p: 1.5, borderRadius: 2, border: "1px solid", borderColor: "grey.200",
        bgcolor: `${tokens.brand.primary}06`, minWidth: 110, textAlign: "center",
      }}
    >
      <Typography variant="h6" fontWeight={700} color={tokens.brand.primary} lineHeight={1.1}>
        {value}
      </Typography>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
    </Box>
  );
}

export function AiMetricsPanel() {
  const [data, setData] = useState<MetricsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    api.getMetrics()
      .then(setData)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", alignItems: "center", height: "100%", pt: 6 }}>
        <CircularProgress size={28} />
      </Box>
    );
  }

  if (error || !data) {
    return (
      <Box sx={{ p: 3, textAlign: "center", color: "text.secondary" }}>
        <QueryStatsOutlinedIcon sx={{ fontSize: 40, opacity: 0.3, mb: 1 }} />
        <Typography variant="body2">No se pudieron cargar las métricas.</Typography>
      </Box>
    );
  }

  const totalRoleQueries = Object.values(data.queries_by_role).reduce((a, b) => a + b, 0) || 1;

  return (
    <Box sx={{ overflowY: "auto", height: "100%", p: 2 }}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 2 }}>
        <QueryStatsOutlinedIcon sx={{ color: tokens.brand.primary }} />
        <Typography variant="subtitle1" fontWeight={700}>Métricas del mes</Typography>
        <Typography variant="caption" color="text.disabled" sx={{ ml: "auto" }}>{data.period}</Typography>
      </Box>

      {/* KPI row */}
      <Box sx={{ display: "flex", gap: 1.5, flexWrap: "wrap", mb: 2.5 }}>
        <KpiCard label="Consultas"      value={data.total_queries} />
        <KpiCard label="Usuarios"       value={data.active_users} />
        <KpiCard label="Costo USD"      value={`$${data.total_cost_usd.toFixed(2)}`} />
        <KpiCard label="Duración prom." value={`${(data.avg_duration_ms / 1000).toFixed(1)}s`} />
      </Box>

      <Divider sx={{ mb: 2 }} />

      {/* Queries by role */}
      <Typography variant="caption" fontWeight={600} color="text.secondary" sx={{ textTransform: "uppercase", letterSpacing: 0.5 }}>
        Consultas por rol
      </Typography>
      <Box sx={{ mt: 1, mb: 2 }}>
        {Object.entries(data.queries_by_role).map(([role, count]) => {
          const pct = Math.round((count / totalRoleQueries) * 100);
          return (
            <Box key={role} sx={{ mb: 1 }}>
              <Box sx={{ display: "flex", justifyContent: "space-between", mb: 0.25 }}>
                <Typography variant="caption">{ROLE_LABELS[role] ?? role}</Typography>
                <Typography variant="caption" color="text.secondary">{count} ({pct}%)</Typography>
              </Box>
              <LinearProgress
                variant="determinate"
                value={pct}
                sx={{
                  height: 6, borderRadius: 3,
                  bgcolor: "grey.100",
                  "& .MuiLinearProgress-bar": { bgcolor: tokens.brand.primary },
                }}
              />
            </Box>
          );
        })}
      </Box>

      {/* Top tool */}
      {data.top_tool && (
        <>
          <Divider sx={{ mb: 2 }} />
          <Typography variant="caption" fontWeight={600} color="text.secondary" sx={{ textTransform: "uppercase", letterSpacing: 0.5 }}>
            Herramienta más usada
          </Typography>
          <Box sx={{ mt: 0.75, p: 1.25, bgcolor: `${tokens.brand.accent}15`, borderRadius: 1.5, display: "inline-block" }}>
            <Typography variant="body2" fontWeight={600}>{data.top_tool}</Typography>
            <Typography variant="caption" color="text.secondary"> · {data.top_tool_count} usos</Typography>
          </Box>
        </>
      )}

      {/* Queries by day (sparkline-style) */}
      {data.queries_by_day.length > 0 && (
        <>
          <Divider sx={{ my: 2 }} />
          <Typography variant="caption" fontWeight={600} color="text.secondary" sx={{ textTransform: "uppercase", letterSpacing: 0.5, display: "block", mb: 1 }}>
            Actividad diaria
          </Typography>
          <Box sx={{ display: "flex", gap: 0.5, alignItems: "flex-end", height: 48 }}>
            {(() => {
              const maxCount = Math.max(...data.queries_by_day.map((d) => d.count), 1);
              return data.queries_by_day.slice(-30).map((d) => (
                <Box
                  key={d.date}
                  title={`${d.date}: ${d.count}`}
                  sx={{
                    flex: 1, minWidth: 3,
                    height: `${Math.max(4, Math.round((d.count / maxCount) * 100))}%`,
                    bgcolor: tokens.brand.primary,
                    borderRadius: "2px 2px 0 0",
                    opacity: 0.7,
                  }}
                />
              ));
            })()}
          </Box>
        </>
      )}
    </Box>
  );
}
