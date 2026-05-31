import { useCallback, useEffect, useState } from "react";
import {
  Alert, Box, Button, Card, CardContent, CircularProgress,
  Divider, FormControl, InputAdornment, InputLabel, LinearProgress,
  MenuItem, Select, Snackbar, Stack, Switch, TextField, Typography,
} from "@mui/material";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import { api, type TenantConfigResponse, type TenantConfigPatch } from "@/api/client";
import { useAuth } from "@/hooks/useAuth";
import { tokens } from "@/theme/tokens";

const MEMORY_OPTIONS = [
  { value: 1,  label: "1 turno" },
  { value: 3,  label: "3 turnos (recomendado)" },
  { value: 5,  label: "5 turnos" },
  { value: 10, label: "10 turnos (mayor costo)" },
];

const ALERT_OPTIONS = [
  { value: 60, label: "60% del presupuesto" },
  { value: 70, label: "70% del presupuesto" },
  { value: 80, label: "80% del presupuesto" },
  { value: 90, label: "90% del presupuesto" },
];

const RATE_FIELDS: Record<string, { key: keyof TenantConfigPatch; label: string }[]> = {
  produccion: [
    { key: "rate_limit_director",   label: "Dirección" },
    { key: "rate_limit_produccion", label: "Producción" },
    { key: "rate_limit_compras",    label: "Compras" },
  ],
  retail: [
    { key: "rate_limit_director",  label: "Dirección" },
    { key: "rate_limit_marca",     label: "Marca" },
    { key: "rate_limit_tienda",    label: "Tienda" },
    { key: "rate_limit_producto",  label: "Producto" },
  ],
};

type Draft = {
  monthly_budget_usd: number;
  budget_alert_pct: number;
  memory_turns: number;
  suggestions_enabled: boolean;
  rate_limits: Record<string, number>;
};

function configToDraft(cfg: TenantConfigResponse): Draft {
  return {
    monthly_budget_usd: cfg.monthly_budget_usd,
    budget_alert_pct:   cfg.budget_alert_pct,
    memory_turns:       cfg.memory_turns,
    suggestions_enabled:cfg.suggestions_enabled,
    rate_limits:        { ...cfg.rate_limits },
  };
}

export function ConfiguracionPage() {
  const { user } = useAuth();
  const [cfg, setCfg] = useState<TenantConfigResponse | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    api.getTenantConfig()
      .then((c) => { setCfg(c); setDraft(configToDraft(c)); })
      .catch(() => setError("No se pudo cargar la configuración."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const hasChanges = cfg && draft
    ? JSON.stringify(configToDraft(cfg)) !== JSON.stringify(draft)
    : false;

  const handleSave = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      const patch: TenantConfigPatch = {
        monthly_budget_usd:  draft.monthly_budget_usd,
        budget_alert_pct:    draft.budget_alert_pct,
        memory_turns:        draft.memory_turns,
        suggestions_enabled: draft.suggestions_enabled,
        ...Object.fromEntries(
          Object.entries(draft.rate_limits).map(([k, v]) => [`rate_limit_${k}`, v])
        ),
      };
      const updated = await api.patchTenantConfig(patch);
      setCfg(updated);
      setDraft(configToDraft(updated));
      setToast("Configuración guardada.");
    } catch {
      setError("Error al guardar. Intentá de nuevo.");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <Box sx={{ display: "flex", justifyContent: "center", pt: 8 }}><CircularProgress /></Box>;

  const vertical = cfg?.vertical ?? user?.vertical ?? "retail";
  const rateFields = RATE_FIELDS[vertical] ?? RATE_FIELDS.retail;
  const spendPct   = cfg ? Math.min((cfg.current_spend_usd / (cfg.monthly_budget_usd || 1)) * 100, 100) : 0;

  return (
    <Box sx={{ maxWidth: 720, mx: "auto", px: 3, py: 4 }}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, mb: 4 }}>
        <SettingsOutlinedIcon sx={{ color: tokens.brand.primary, fontSize: 28 }} />
        <Box>
          <Typography variant="h5" fontWeight={700}>Asistente IA — Configuración</Typography>
          <Typography variant="body2" color="text.secondary">
            Presupuesto, memoria conversacional, límites por rol y sugerencias.
          </Typography>
        </Box>
      </Box>

      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>{error}</Alert>}

      <Stack spacing={2.5}>
        {/* Card 1: Gasto */}
        <Card variant="outlined">
          <CardContent>
            <Typography variant="subtitle2" fontWeight={600} gutterBottom>Gasto este mes</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
              ${cfg?.current_spend_usd.toFixed(2) ?? "0.00"} / ${cfg?.monthly_budget_usd.toFixed(2) ?? "0.00"}
              {" "}· {spendPct.toFixed(0)}% del presupuesto consumido
            </Typography>
            <LinearProgress
              variant="determinate"
              value={spendPct}
              sx={{
                height: 8, borderRadius: 4,
                "& .MuiLinearProgress-bar": {
                  bgcolor: spendPct > 80 ? "error.main" : spendPct > 50 ? "warning.main" : tokens.brand.primary,
                },
              }}
            />
          </CardContent>
        </Card>

        {/* Card 2: Presupuesto */}
        <Card variant="outlined">
          <CardContent>
            <Typography variant="subtitle2" fontWeight={600} gutterBottom>Presupuesto mensual</Typography>
            <Stack direction="row" spacing={2}>
              <TextField
                label="Monto USD"
                type="number"
                size="small"
                value={draft?.monthly_budget_usd ?? 0}
                onChange={(e) => setDraft((d) => d ? { ...d, monthly_budget_usd: Number(e.target.value) } : d)}
                InputProps={{ startAdornment: <InputAdornment position="start">$</InputAdornment> }}
                helperText="0 = sin límite"
                sx={{ width: 180 }}
              />
              <FormControl size="small" sx={{ minWidth: 200 }}>
                <InputLabel>Alerta de gasto</InputLabel>
                <Select
                  label="Alerta de gasto"
                  value={draft?.budget_alert_pct ?? 80}
                  onChange={(e) => setDraft((d) => d ? { ...d, budget_alert_pct: Number(e.target.value) } : d)}
                >
                  {ALERT_OPTIONS.map((o) => <MenuItem key={o.value} value={o.value}>{o.label}</MenuItem>)}
                </Select>
              </FormControl>
            </Stack>
          </CardContent>
        </Card>

        {/* Card 3: Memoria */}
        <Card variant="outlined">
          <CardContent>
            <Typography variant="subtitle2" fontWeight={600} gutterBottom>Memoria conversacional</Typography>
            <FormControl size="small" sx={{ minWidth: 260 }}>
              <InputLabel>Turnos a recordar</InputLabel>
              <Select
                label="Turnos a recordar"
                value={draft?.memory_turns ?? 3}
                onChange={(e) => setDraft((d) => d ? { ...d, memory_turns: Number(e.target.value) } : d)}
              >
                {MEMORY_OPTIONS.map((o) => <MenuItem key={o.value} value={o.value}>{o.label}</MenuItem>)}
              </Select>
            </FormControl>
            <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
              Cuántos turnos previos lee el asistente por consulta
            </Typography>
          </CardContent>
        </Card>

        {/* Card 4: Rate limits */}
        <Card variant="outlined">
          <CardContent>
            <Typography variant="subtitle2" fontWeight={600} gutterBottom>
              Consultas máximas por hora (por usuario)
            </Typography>
            <Stack direction="row" flexWrap="wrap" gap={2} sx={{ mt: 1 }}>
              {rateFields.map(({ key, label }) => {
                const rlKey = key.replace("rate_limit_", "");
                return (
                  <TextField
                    key={key}
                    label={label}
                    type="number"
                    size="small"
                    sx={{ width: 130 }}
                    value={draft?.rate_limits[rlKey] ?? 30}
                    onChange={(e) =>
                      setDraft((d) =>
                        d ? { ...d, rate_limits: { ...d.rate_limits, [rlKey]: Number(e.target.value) } } : d
                      )
                    }
                  />
                );
              })}
            </Stack>
          </CardContent>
        </Card>

        {/* Card 5: Sugerencias */}
        <Card variant="outlined">
          <CardContent>
            <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <Box>
                <Typography variant="subtitle2" fontWeight={600}>Sugerencias dinámicas</Typography>
                <Typography variant="caption" color="text.secondary">
                  Genera 3 preguntas iniciales con IA según las alertas activas. Si lo apagás, mostramos preguntas fijas por rol.
                </Typography>
              </Box>
              <Switch
                checked={draft?.suggestions_enabled ?? true}
                onChange={(e) => setDraft((d) => d ? { ...d, suggestions_enabled: e.target.checked } : d)}
                color="primary"
              />
            </Box>
          </CardContent>
        </Card>
      </Stack>

      <Divider sx={{ my: 3 }} />

      <Box sx={{ display: "flex", gap: 1.5, justifyContent: "flex-end" }}>
        <Button
          variant="outlined"
          disabled={!hasChanges || saving}
          onClick={() => cfg && setDraft(configToDraft(cfg))}
        >
          Descartar
        </Button>
        <Button
          variant="contained"
          disabled={!hasChanges || saving}
          onClick={() => { void handleSave(); }}
          sx={{ bgcolor: tokens.brand.primary, "&:hover": { bgcolor: "#0a8a78" } }}
        >
          {saving ? <CircularProgress size={20} color="inherit" /> : "Guardar"}
        </Button>
      </Box>

      <Snackbar
        open={!!toast}
        autoHideDuration={3000}
        onClose={() => setToast(null)}
        message={toast}
      />
    </Box>
  );
}
