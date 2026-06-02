import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert, Box, Button, Chip, CircularProgress, FormControl, InputLabel,
  MenuItem, Paper, Select, Stack, Table, TableBody, TableCell, TableContainer,
  TableHead, TablePagination, TableRow, Tooltip, Typography,
} from "@mui/material";
import ArticleOutlinedIcon from "@mui/icons-material/ArticleOutlined";
import RefreshOutlinedIcon from "@mui/icons-material/RefreshOutlined";
import { api, type AdminTenant, type LogRow, type LogsResponse } from "@/api/client";
import { tokens } from "@/theme/tokens";

type StatusFilter = "" | "SUCCESS" | "ERROR" | "PARTIAL";

const STATUS_COLOR: Record<string, "success" | "error" | "warning" | "default"> = {
  SUCCESS: "success",
  ERROR: "error",
  PARTIAL: "warning",
};

function formatTimestamp(ts: string | null): string {
  if (!ts) return "—";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return ts;
  return d.toLocaleString("es-UY", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function formatCost(usd: number): string {
  if (usd === 0) return "—";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

export function AdminLogs() {
  const [tenants, setTenants] = useState<AdminTenant[]>([]);
  const [tenantFilter, setTenantFilter] = useState<number | "">("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("");
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(50);

  const [data, setData] = useState<LogsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Load tenants once for the dropdown
  useEffect(() => {
    api.adminGetTenants().then(setTenants).catch(() => null);
  }, []);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .adminGetLogs({
        tenant_id: tenantFilter === "" ? undefined : tenantFilter,
        status_filter: statusFilter === "" ? undefined : statusFilter,
        limit: rowsPerPage,
        offset: page * rowsPerPage,
      })
      .then(setData)
      .catch((e) => setError(e?.response?.data?.detail ?? "Error al cargar logs"))
      .finally(() => setLoading(false));
  }, [tenantFilter, statusFilter, page, rowsPerPage]);

  useEffect(() => { load(); }, [load]);

  const handleResetPage = () => setPage(0);
  const onTenantChange = (v: number | "") => { setTenantFilter(v); handleResetPage(); };
  const onStatusChange = (v: StatusFilter) => { setStatusFilter(v); handleResetPage(); };

  // Map platform_tenant_id → tenant name for tenants the dropdown knows
  const tenantNameByPid = useMemo(() => {
    const m = new Map<number, string>();
    for (const t of tenants) {
      if (t.platform_tenant_id != null) m.set(t.platform_tenant_id, t.name);
    }
    return m;
  }, [tenants]);

  const resolveTenantName = (row: LogRow): string =>
    row.tenant_name ?? tenantNameByPid.get(row.tenant_id) ?? `Tenant ${row.tenant_id}`;

  return (
    <Box sx={{ p: 4, maxWidth: 1200, mx: "auto" }}>
      <Stack direction="row" alignItems="center" spacing={1.5} sx={{ mb: 3 }}>
        <ArticleOutlinedIcon sx={{ color: tokens.brand.primary, fontSize: 28 }} />
        <Box sx={{ flex: 1 }}>
          <Typography variant="h5" fontWeight={700}>Logs</Typography>
          <Typography variant="body2" color="text.secondary">
            Audit trail cross-tenant. Mostrando los últimos chats.
          </Typography>
        </Box>
        <Tooltip title="Refrescar">
          <span>
            <Button
              startIcon={<RefreshOutlinedIcon />}
              onClick={load}
              disabled={loading}
              size="small"
            >
              Refrescar
            </Button>
          </span>
        </Tooltip>
      </Stack>

      {/* Filters */}
      <Stack
        direction={{ xs: "column", sm: "row" }}
        spacing={2}
        sx={{ mb: 2 }}
      >
        <FormControl size="small" sx={{ minWidth: 220 }}>
          <InputLabel>Tenant</InputLabel>
          <Select
            label="Tenant"
            value={tenantFilter === "" ? "" : String(tenantFilter)}
            onChange={(e) =>
              onTenantChange(e.target.value === "" ? "" : Number(e.target.value))
            }
          >
            <MenuItem value="">
              <em>Todos</em>
            </MenuItem>
            {tenants
              .filter((t) => t.platform_tenant_id != null)
              .map((t) => (
                <MenuItem key={t.id} value={String(t.platform_tenant_id)}>
                  {t.name} <Typography component="span" sx={{ ml: 1, color: "text.disabled", fontSize: "0.75rem" }}>
                    [id {t.platform_tenant_id}]
                  </Typography>
                </MenuItem>
              ))}
          </Select>
        </FormControl>

        <FormControl size="small" sx={{ minWidth: 160 }}>
          <InputLabel>Estado</InputLabel>
          <Select
            label="Estado"
            value={statusFilter}
            onChange={(e) => onStatusChange(e.target.value as StatusFilter)}
          >
            <MenuItem value=""><em>Todos</em></MenuItem>
            <MenuItem value="SUCCESS">SUCCESS</MenuItem>
            <MenuItem value="ERROR">ERROR</MenuItem>
            <MenuItem value="PARTIAL">PARTIAL</MenuItem>
          </Select>
        </FormControl>
      </Stack>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {loading && !data ? (
        <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
          <CircularProgress />
        </Box>
      ) : data && data.rows.length === 0 ? (
        <Alert severity="info">
          Sin actividad para los filtros actuales.
        </Alert>
      ) : data ? (
        <Paper variant="outlined">
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  {["Fecha", "Tenant", "Rol", "Estado", "Tokens", "Costo", "Preview"].map((h) => (
                    <TableCell key={h} sx={{ fontWeight: 600 }}>{h}</TableCell>
                  ))}
                </TableRow>
              </TableHead>
              <TableBody>
                {data.rows.map((row, i) => (
                  <TableRow key={`${row.conversation_id ?? "x"}-${i}`} hover>
                    <TableCell sx={{ whiteSpace: "nowrap", fontSize: "0.78rem" }}>
                      {formatTimestamp(row.timestamp)}
                    </TableCell>
                    <TableCell sx={{ whiteSpace: "nowrap" }}>
                      <Stack direction="row" spacing={0.5} alignItems="center">
                        <Typography variant="body2">{resolveTenantName(row)}</Typography>
                        <Chip
                          label={row.source}
                          size="small"
                          variant="outlined"
                          sx={{ height: 16, fontSize: "0.6rem", textTransform: "uppercase" }}
                        />
                      </Stack>
                    </TableCell>
                    <TableCell sx={{ fontSize: "0.78rem" }}>{row.user_role || "—"}</TableCell>
                    <TableCell>
                      <Chip
                        label={row.status}
                        size="small"
                        color={STATUS_COLOR[row.status] ?? "default"}
                        sx={{ height: 20, fontSize: "0.7rem" }}
                      />
                    </TableCell>
                    <TableCell align="right" sx={{ fontSize: "0.78rem" }}>
                      {row.tokens > 0 ? row.tokens.toLocaleString("es-UY") : "—"}
                    </TableCell>
                    <TableCell align="right" sx={{ fontSize: "0.78rem" }}>
                      {formatCost(row.cost_usd)}
                    </TableCell>
                    <TableCell sx={{ maxWidth: 340, fontSize: "0.78rem", color: "text.secondary" }}>
                      <Tooltip title={row.preview} placement="left">
                        <Box sx={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {row.preview || "—"}
                        </Box>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
          <TablePagination
            component="div"
            count={data.total}
            page={page}
            onPageChange={(_, p) => setPage(p)}
            rowsPerPage={rowsPerPage}
            onRowsPerPageChange={(e) => {
              setRowsPerPage(parseInt(e.target.value, 10));
              setPage(0);
            }}
            rowsPerPageOptions={[25, 50, 100, 200]}
            labelRowsPerPage="Filas por página"
          />
        </Paper>
      ) : null}
    </Box>
  );
}
