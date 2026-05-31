import { useState } from "react";
import { Box, IconButton, InputBase, Paper, Typography } from "@mui/material";
import ArrowUpwardIcon from "@mui/icons-material/ArrowUpward";
import { tokens } from "@/theme/tokens";

interface Props {
  onSend: (text: string) => void;
  disabled?: boolean;
}

export function ChatInput({ onSend, disabled }: Props) {
  const [value, setValue] = useState("");

  const handleSend = () => {
    const t = value.trim();
    if (!t || disabled) return;
    setValue("");
    onSend(t);
  };

  return (
    <Box sx={{ maxWidth: tokens.chat.maxWidth, mx: "auto", width: "100%", px: 2, pb: 2 }}>
      <Paper
        elevation={0}
        sx={{
          display: "flex", alignItems: "flex-end", gap: 1,
          border: "1.5px solid",
          borderColor: "grey.300",
          borderRadius: 6,
          px: 2, py: 1,
          transition: "border-color 0.2s, box-shadow 0.2s",
          "&:focus-within": {
            borderColor: tokens.brand.primary,
            boxShadow: `0 0 0 3px ${tokens.brand.primary}22`,
          },
        }}
      >
        <InputBase
          fullWidth
          multiline
          maxRows={5}
          placeholder="Escribí tu pregunta…"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleSend();
            }
          }}
          disabled={disabled}
          sx={{ fontSize: "0.9rem", lineHeight: 1.5 }}
        />
        <IconButton
          size="small"
          onClick={handleSend}
          disabled={disabled || !value.trim()}
          sx={{
            flexShrink: 0,
            bgcolor: value.trim() && !disabled ? tokens.brand.primary : "grey.300",
            color: "white",
            width: 32, height: 32,
            "&:hover": { bgcolor: value.trim() && !disabled ? "#0a8a78" : "grey.300" },
            "&.Mui-disabled": { bgcolor: "grey.300", color: "white" },
            transition: "background-color 0.2s",
          }}
        >
          <ArrowUpwardIcon sx={{ fontSize: 18 }} />
        </IconButton>
      </Paper>
      <Typography
        variant="caption"
        sx={{ display: "block", textAlign: "center", mt: 0.75, color: "text.disabled" }}
      >
        Enter para enviar · Shift+Enter para nueva línea
      </Typography>
    </Box>
  );
}
