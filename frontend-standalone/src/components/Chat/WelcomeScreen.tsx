import { Box, Chip, Typography } from "@mui/material";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import { tokens } from "@/theme/tokens";

interface Props {
  vertical: string | null;
  suggestions: string[];
  onSuggestion: (s: string) => void;
}

const WELCOME_TEXT: Record<string, string> = {
  produccion: "¿Qué producimos hoy?",
  retail:     "¿Cómo van las ventas?",
};

export function WelcomeScreen({ vertical, suggestions, onSuggestion }: Props) {
  const greeting = WELCOME_TEXT[vertical ?? "retail"] ?? "¿En qué puedo ayudarte?";

  return (
    <Box
      sx={{
        flex: 1, display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        gap: 3, p: 4, maxWidth: tokens.chat.maxWidth, mx: "auto", width: "100%",
      }}
    >
      <Box
        sx={{
          width: 72, height: 72, borderRadius: "50%",
          bgcolor: `${tokens.brand.primary}18`,
          display: "flex", alignItems: "center", justifyContent: "center",
          animation: "pulse 2.5s ease-in-out infinite",
          "@keyframes pulse": {
            "0%,100%": { transform: "scale(1)", opacity: 1 },
            "50%":     { transform: "scale(1.08)", opacity: 0.85 },
          },
        }}
      >
        <AutoAwesomeIcon sx={{ fontSize: 36, color: tokens.brand.primary }} />
      </Box>

      <Typography variant="h5" fontWeight={700} textAlign="center" color="text.primary">
        {greeting}
      </Typography>

      {suggestions.length > 0 && (
        <Box sx={{ display: "flex", flexDirection: "column", gap: 1.5, width: "100%", maxWidth: 520 }}>
          {suggestions.map((s) => (
            <Chip
              key={s}
              label={s}
              onClick={() => onSuggestion(s)}
              variant="outlined"
              sx={{
                cursor: "pointer",
                justifyContent: "flex-start",
                height: "auto",
                py: 1.25, px: 2,
                fontSize: "0.875rem",
                borderRadius: 3,
                borderColor: "grey.300",
                "& .MuiChip-label": { whiteSpace: "normal", textAlign: "left" },
                "&:hover": { bgcolor: `${tokens.brand.primary}10`, borderColor: tokens.brand.primary },
              }}
            />
          ))}
        </Box>
      )}
    </Box>
  );
}
