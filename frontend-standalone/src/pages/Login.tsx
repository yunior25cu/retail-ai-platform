import { useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  TextField,
  Typography,
  Paper,
} from "@mui/material";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import { useAuth } from "@/hooks/useAuth";

export function Login() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [slug, setSlug] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Auto-suggest slug when email ends in known domain
  const handleEmailBlur = () => {
    if (!slug && email.includes("@")) {
      const isAdmin = email.toLowerCase().startsWith("admin@");
      if (isAdmin) setSlug("admin");
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login({ email: email.trim(), password, tenant_slug: slug.trim() });
    } catch {
      // Never reveal whether the email exists
      setError("Credenciales inválidas. Verificá tu email y contraseña.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box
      sx={{
        minHeight: "100vh",
        bgcolor: "grey.50",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        p: 2,
      }}
    >
      <Paper elevation={3} sx={{ width: "100%", maxWidth: 400, p: 4 }}>
        <Box sx={{ display: "flex", flexDirection: "column", alignItems: "center", mb: 3 }}>
          <AutoAwesomeIcon sx={{ fontSize: 40, color: "primary.main", mb: 1 }} />
          <Typography variant="h5" fontWeight={700}>
            {import.meta.env.VITE_APP_NAME ?? "IA Asistente"}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Iniciá sesión para continuar
          </Typography>
        </Box>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        <Box component="form" onSubmit={(e) => { void handleSubmit(e); }} noValidate>
          <TextField
            fullWidth
            label="Email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onBlur={handleEmailBlur}
            margin="normal"
            required
            autoFocus
            autoComplete="email"
            disabled={loading}
          />
          <TextField
            fullWidth
            label="Contraseña"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            margin="normal"
            required
            autoComplete="current-password"
            disabled={loading}
          />
          <TextField
            fullWidth
            label="Empresa (slug)"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            margin="normal"
            required
            disabled={loading}
            helperText="Identificador de tu empresa (ej: prolimpio). Administradores del sistema: usar 'admin'"
          />
          <Button
            type="submit"
            fullWidth
            variant="contained"
            size="large"
            sx={{ mt: 3 }}
            disabled={loading || !email || !password || !slug}
          >
            {loading ? <CircularProgress size={24} color="inherit" /> : "Ingresar"}
          </Button>
        </Box>
      </Paper>
    </Box>
  );
}
