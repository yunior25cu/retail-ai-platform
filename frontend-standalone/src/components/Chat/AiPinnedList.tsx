import { Box, IconButton, Tooltip, Typography } from "@mui/material";
import PushPinIcon from "@mui/icons-material/PushPin";
import type { PinnedMessage } from "@/utils/pins";
import { tokens } from "@/theme/tokens";

interface Props {
  pins: PinnedMessage[];
  onUnpin: (id: string) => void;
  onOpenConversation: (conversationId: string) => void;
}

function formatRelative(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1)    return "Ahora";
  if (m < 60)   return `Hace ${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24)   return `Hace ${h}h`;
  const d = Math.floor(h / 24);
  if (d === 1)  return "Ayer";
  return new Date(iso).toLocaleDateString("es-UY", { day: "2-digit", month: "2-digit" });
}

export function AiPinnedList({ pins, onUnpin, onOpenConversation }: Props) {
  if (pins.length === 0) {
    return (
      <Box sx={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", color: "text.disabled", gap: 1 }}>
        <PushPinIcon sx={{ fontSize: 36, opacity: 0.3 }} />
        <Typography variant="body2" color="text.disabled">
          No hay respuestas ancladas
        </Typography>
        <Typography variant="caption" color="text.disabled" textAlign="center" sx={{ maxWidth: 200 }}>
          Usá el ícono 📌 en una respuesta del asistente para anclarla aquí
        </Typography>
      </Box>
    );
  }

  return (
    <Box sx={{ overflowY: "auto", height: "100%", p: 1.5 }}>
      <Typography variant="caption" color="text.disabled" sx={{ px: 0.5, display: "block", mb: 1 }}>
        {pins.length} respuesta{pins.length !== 1 ? "s" : ""} anclada{pins.length !== 1 ? "s" : ""}
      </Typography>
      {pins.map((pin) => (
        <Box
          key={pin.id}
          sx={{
            mb: 1, p: 1.25, borderRadius: 2,
            border: "1px solid", borderColor: "grey.200",
            bgcolor: `${tokens.brand.primary}06`,
            cursor: "pointer",
            "&:hover": { borderColor: tokens.brand.primary, bgcolor: `${tokens.brand.primary}10` },
            position: "relative",
          }}
          onClick={() => onOpenConversation(pin.conversationId)}
        >
          <Typography
            variant="body2"
            sx={{
              fontSize: "0.8rem",
              display: "-webkit-box",
              WebkitLineClamp: 3,
              WebkitBoxOrient: "vertical",
              overflow: "hidden",
              pr: 3,
            }}
          >
            {pin.content}
          </Typography>
          <Typography variant="caption" color="text.disabled" sx={{ display: "block", mt: 0.5, fontSize: "0.68rem" }}>
            {formatRelative(pin.pinnedAt)}
          </Typography>
          <Tooltip title="Desanclar">
            <IconButton
              size="small"
              onClick={(e) => { e.stopPropagation(); onUnpin(pin.id); }}
              sx={{ position: "absolute", top: 6, right: 6, p: 0.25, color: tokens.brand.primary }}
            >
              <PushPinIcon sx={{ fontSize: 14 }} />
            </IconButton>
          </Tooltip>
        </Box>
      ))}
    </Box>
  );
}
