import { Box, AppBar, Toolbar, Typography, Button, Avatar } from "@mui/material";
import LogoutIcon from "@mui/icons-material/Logout";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import { ChatInterface } from "@/components/ChatInterface";
import { useAuth } from "@/hooks/useAuth";

export function Chat() {
  const { user, logout } = useAuth();

  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <AppBar position="static" elevation={1} color="default">
        <Toolbar variant="dense">
          <AutoAwesomeIcon color="primary" sx={{ mr: 1 }} />
          <Typography variant="subtitle1" fontWeight={600} sx={{ flex: 1 }}>
            {import.meta.env.VITE_APP_NAME ?? "IA Asistente"}
          </Typography>
          {user && (
            <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
              <Avatar sx={{ width: 28, height: 28, bgcolor: "primary.main", fontSize: 12 }}>
                {user.email[0].toUpperCase()}
              </Avatar>
              <Typography variant="body2" color="text.secondary" sx={{ display: { xs: "none", sm: "block" } }}>
                {user.email}
              </Typography>
              <Button
                size="small"
                color="inherit"
                startIcon={<LogoutIcon />}
                onClick={() => { void logout(); }}
              >
                Salir
              </Button>
            </Box>
          )}
        </Toolbar>
      </AppBar>

      <Box sx={{ flex: 1, overflow: "hidden", display: "flex" }}>
        <ChatInterface />
      </Box>
    </Box>
  );
}
