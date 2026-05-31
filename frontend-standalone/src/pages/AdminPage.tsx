import { useCallback, useEffect, useState } from "react";
import {
  Alert, Box, Button, Chip, CircularProgress, Dialog, DialogActions,
  DialogContent, DialogTitle, FormControl, IconButton, InputLabel,
  MenuItem, Paper, Select, Stack, Switch, Tab, Table, TableBody,
  TableCell, TableContainer, TableHead, TableRow, Tabs, TextField,
  Tooltip, Typography,
} from "@mui/material";
import AdminPanelSettingsOutlinedIcon from "@mui/icons-material/AdminPanelSettingsOutlined";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import PersonAddOutlinedIcon from "@mui/icons-material/PersonAddOutlined";
import AddBusinessOutlinedIcon from "@mui/icons-material/AddBusinessOutlined";
import { api, type AdminTenant, type AdminUser, type VerticalOut } from "@/api/client";
import { tokens } from "@/theme/tokens";

// ── Tenants tab ───────────────────────────────────────────────────────────────

function TenantsTab() {
  const [tenants, setTenants] = useState<AdminTenant[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState({ name: "", slug: "", vertical: "retail", plan: "starter", platform_tenant_id: "" });
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    api.adminGetTenants().then(setTenants);
  }, []);
  useEffect(() => { load(); }, [load]);

  const handleCreate = async () => {
    setSaving(true);
    try {
      await api.adminCreateTenant({
        name: form.name, slug: form.slug, vertical: form.vertical,
        plan: form.plan, is_active: true,
        platform_tenant_id: form.platform_tenant_id ? Number(form.platform_tenant_id) : null,
        created_at: new Date().toISOString(),
      } as Omit<AdminTenant, "id" | "is_active" | "created_at">);
      setDialogOpen(false);
      load();
    } finally { setSaving(false); }
  };

  const toggleActive = async (t: AdminTenant) => {
    await api.adminPatchTenant(t.id, { is_active: !t.is_active });
    load();
  };


  return (
    <>
      <Box sx={{ display: "flex", justifyContent: "flex-end", mb: 2 }}>
        <Button startIcon={<AddBusinessOutlinedIcon />} variant="contained"
          sx={{ bgcolor: tokens.brand.primary }} onClick={() => setDialogOpen(true)}>
          Nuevo tenant
        </Button>
      </Box>
      <TableContainer component={Paper} variant="outlined">
        <Table size="small">
          <TableHead>
            <TableRow>
              {["Nombre", "Slug", "Vertical", "Plan", "Platform ID", "Activo"].map((h) => (
                <TableCell key={h} sx={{ fontWeight: 600 }}>{h}</TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {tenants.map((t) => (
              <TableRow key={t.id} hover>
                <TableCell>{t.name}</TableCell>
                <TableCell><code>{t.slug}</code></TableCell>
                <TableCell><Chip label={t.vertical} size="small" color={t.vertical === "produccion" ? "primary" : "default"} /></TableCell>
                <TableCell>{t.plan}</TableCell>
                <TableCell>{t.platform_tenant_id ?? "—"}</TableCell>
                <TableCell>
                  <Switch size="small" checked={t.is_active} onChange={() => { void toggleActive(t); }} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Nuevo tenant</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField label="Nombre" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value, slug: e.target.value.toLowerCase().replace(/\s+/g, "-") }))} />
            <TextField label="Slug" value={form.slug} onChange={(e) => setForm((f) => ({ ...f, slug: e.target.value }))} />
            <FormControl>
              <InputLabel>Vertical</InputLabel>
              <Select label="Vertical" value={form.vertical} onChange={(e) => setForm((f) => ({ ...f, vertical: e.target.value }))}>
                <MenuItem value="retail">Retail</MenuItem>
                <MenuItem value="produccion">Producción</MenuItem>
              </Select>
            </FormControl>
            <FormControl>
              <InputLabel>Plan</InputLabel>
              <Select label="Plan" value={form.plan} onChange={(e) => setForm((f) => ({ ...f, plan: e.target.value }))}>
                <MenuItem value="starter">Starter</MenuItem>
                <MenuItem value="professional">Professional</MenuItem>
                <MenuItem value="enterprise">Enterprise</MenuItem>
              </Select>
            </FormControl>
            <TextField label="Platform tenant ID (opcional)" value={form.platform_tenant_id}
              onChange={(e) => setForm((f) => ({ ...f, platform_tenant_id: e.target.value }))}
              helperText="ID del tenant en la plataforma Gold (ej: 24)" />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>Cancelar</Button>
          <Button variant="contained" disabled={!form.name || saving} onClick={() => { void handleCreate(); }}
            sx={{ bgcolor: tokens.brand.primary }}>
            {saving ? <CircularProgress size={18} color="inherit" /> : "Crear"}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}

// ── Users tab ─────────────────────────────────────────────────────────────────

function UsersTab() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [tenants, setTenants] = useState<AdminTenant[]>([]);
  const [filterTenant, setFilterTenant] = useState<number | "">("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editUser, setEditUser] = useState<AdminUser | null>(null);
  const [form, setForm] = useState({ email: "", password: "", role: "produccion", full_name: "", tenant_id: "" });
  const [editForm, setEditForm] = useState({ role: "", is_active: true });
  const [saving, setSaving] = useState(false);

  const load = useCallback((tid?: number) => {
    api.adminGetUsers(tid).then(setUsers);
  }, []);

  useEffect(() => {
    api.adminGetTenants().then(setTenants);
    load();
  }, [load]);

  const selectedTenant = filterTenant !== "" ? tenants.find((t) => t.id === filterTenant) : null;
  const vertical = selectedTenant?.vertical ?? "produccion";
  const roleOptions = vertical === "produccion"
    ? ["direccion", "produccion", "compras", "super_admin"]
    : ["direccion", "marca", "tienda", "sku", "super_admin"];

  return (
    <>
      <Box sx={{ display: "flex", justifyContent: "space-between", mb: 2, alignItems: "center" }}>
        <FormControl size="small" sx={{ minWidth: 200 }}>
          <InputLabel>Filtrar por tenant</InputLabel>
          <Select label="Filtrar por tenant" value={filterTenant}
            onChange={(e) => {
              const v = e.target.value as number | "";
              setFilterTenant(v);
              load(v !== "" ? v : undefined);
            }}>
            <MenuItem value="">Todos</MenuItem>
            {tenants.map((t) => <MenuItem key={t.id} value={t.id}>{t.name}</MenuItem>)}
          </Select>
        </FormControl>
        <Button startIcon={<PersonAddOutlinedIcon />} variant="contained"
          sx={{ bgcolor: tokens.brand.primary }} onClick={() => setDialogOpen(true)}>
          Invitar usuario
        </Button>
      </Box>

      <TableContainer component={Paper} variant="outlined">
        <Table size="small">
          <TableHead>
            <TableRow>
              {["Email", "Rol", "Tenant ID", "Activo", "Último login", ""].map((h) => (
                <TableCell key={h} sx={{ fontWeight: 600 }}>{h}</TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {users.map((u) => (
              <TableRow key={u.id} hover>
                <TableCell>{u.email}</TableCell>
                <TableCell><Chip label={u.role} size="small" /></TableCell>
                <TableCell>{u.tenant_id}</TableCell>
                <TableCell>
                  <Switch size="small" checked={u.is_active}
                    onChange={async () => { await api.adminPatchUser(u.id, { is_active: !u.is_active }); load(filterTenant !== "" ? filterTenant : undefined); }} />
                </TableCell>
                <TableCell sx={{ fontSize: "0.78rem", color: "text.secondary" }}>
                  {u.last_login_at ? new Date(u.last_login_at).toLocaleDateString("es-UY") : "—"}
                </TableCell>
                <TableCell>
                  <Tooltip title="Editar rol">
                    <IconButton size="small" onClick={() => { setEditUser(u); setEditForm({ role: u.role, is_active: u.is_active }); }}>
                      <EditOutlinedIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Invite dialog */}
      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Invitar usuario</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField label="Email" type="email" value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} />
            <TextField label="Contraseña" type="password" value={form.password} onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))} />
            <TextField label="Nombre completo (opcional)" value={form.full_name} onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))} />
            <FormControl>
              <InputLabel>Tenant</InputLabel>
              <Select label="Tenant" value={form.tenant_id} onChange={(e) => setForm((f) => ({ ...f, tenant_id: String(e.target.value) }))}>
                {tenants.map((t) => <MenuItem key={t.id} value={t.id}>{t.name}</MenuItem>)}
              </Select>
            </FormControl>
            <FormControl>
              <InputLabel>Rol</InputLabel>
              <Select label="Rol" value={form.role} onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}>
                {["direccion", "produccion", "compras", "marca", "tienda", "sku", "super_admin"].map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}
              </Select>
            </FormControl>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>Cancelar</Button>
          <Button variant="contained" disabled={!form.email || !form.password || !form.tenant_id || saving}
            onClick={async () => {
              setSaving(true);
              try {
                await api.adminInviteUser({ email: form.email, password: form.password, role: form.role, full_name: form.full_name || undefined, tenant_id: Number(form.tenant_id) });
                setDialogOpen(false);
                load(filterTenant !== "" ? filterTenant : undefined);
              } finally { setSaving(false); }
            }}
            sx={{ bgcolor: tokens.brand.primary }}>
            {saving ? <CircularProgress size={18} color="inherit" /> : "Invitar"}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Edit role dialog */}
      <Dialog open={!!editUser} onClose={() => setEditUser(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Editar usuario</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField label="Email" value={editUser?.email ?? ""} disabled />
            <FormControl>
              <InputLabel>Rol</InputLabel>
              <Select label="Rol" value={editForm.role} onChange={(e) => setEditForm((f) => ({ ...f, role: e.target.value }))}>
                {roleOptions.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}
              </Select>
            </FormControl>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditUser(null)}>Cancelar</Button>
          <Button variant="contained" disabled={saving}
            onClick={async () => {
              if (!editUser) return;
              setSaving(true);
              try {
                await api.adminPatchUser(editUser.id, { role: editForm.role });
                setEditUser(null);
                load(filterTenant !== "" ? filterTenant : undefined);
              } finally { setSaving(false); }
            }}
            sx={{ bgcolor: tokens.brand.primary }}>
            {saving ? <CircularProgress size={18} color="inherit" /> : "Guardar"}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}

// ── Verticals tab ─────────────────────────────────────────────────────────────

function VerticalesTab() {
  const [verticals, setVerticals] = useState<VerticalOut[]>([]);
  useEffect(() => { api.adminGetVerticals().then(setVerticals).catch(() => null); }, []);
  return (
    <TableContainer component={Paper} variant="outlined">
      <Table size="small">
        <TableHead>
          <TableRow>
            {["Vertical", "Nombre", "Tools activos", "Tenants"].map((h) => (
              <TableCell key={h} sx={{ fontWeight: 600 }}>{h}</TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {verticals.map((v) => (
            <TableRow key={v.name}>
              <TableCell><code>{v.name}</code></TableCell>
              <TableCell>{v.label}</TableCell>
              <TableCell>{v.tool_count}</TableCell>
              <TableCell>{v.tenant_count}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function AdminPage() {
  const [tab, setTab] = useState(0);
  return (
    <Box sx={{ maxWidth: 960, mx: "auto", px: 3, py: 4 }}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, mb: 3 }}>
        <AdminPanelSettingsOutlinedIcon sx={{ color: tokens.brand.primary, fontSize: 28 }} />
        <Typography variant="h5" fontWeight={700}>Administración</Typography>
      </Box>
      <Alert severity="info" sx={{ mb: 3 }}>
        Esta sección es visible solo para <strong>super_admin</strong>.
      </Alert>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 3, borderBottom: 1, borderColor: "divider" }}>
        <Tab label="Tenants" />
        <Tab label="Usuarios" />
        <Tab label="Verticales" />
      </Tabs>
      {tab === 0 && <TenantsTab />}
      {tab === 1 && <UsersTab />}
      {tab === 2 && <VerticalesTab />}
    </Box>
  );
}
