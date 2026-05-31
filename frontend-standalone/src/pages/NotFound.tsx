import { Box, Button, Typography } from "@mui/material";
import { useNavigate } from "react-router-dom";

export function NotFound() {
  const navigate = useNavigate();
  return (
    <Box
      sx={{
        height: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 2,
      }}
    >
      <Typography variant="h2" fontWeight={700} color="text.disabled">
        404
      </Typography>
      <Typography color="text.secondary">Página no encontrada</Typography>
      <Button variant="contained" onClick={() => navigate("/")}>
        Volver al inicio
      </Button>
    </Box>
  );
}
