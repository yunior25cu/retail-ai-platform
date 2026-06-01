import { useState } from "react";
import { Box, Button, CircularProgress, Popover, TextField, Typography } from "@mui/material";
import { api } from "@/api/client";
import { tokens } from "@/theme/tokens";

interface Props {
  anchorEl: HTMLElement | null;
  requestId: string;
  onClose: () => void;
  onSubmitted: () => void;
}

export function FeedbackPopover({ anchorEl, requestId, onClose, onSubmitted }: Props) {
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async (includeComment: boolean) => {
    setSubmitting(true);
    try {
      await api.submitFeedback({
        request_id: requestId,
        rating: "negative",
        comment: includeComment && comment.trim() ? comment.trim() : undefined,
      });
    } catch {
      // best-effort — don't block UX on feedback failure
    } finally {
      setSubmitting(false);
      setComment("");
      onSubmitted();
    }
  };

  return (
    <Popover
      open={Boolean(anchorEl)}
      anchorEl={anchorEl}
      onClose={onClose}
      anchorOrigin={{ vertical: "bottom", horizontal: "left" }}
      transformOrigin={{ vertical: "top", horizontal: "left" }}
      PaperProps={{ sx: { p: 2, maxWidth: 300, borderRadius: 2 } }}
    >
      <Typography variant="subtitle2" fontWeight={600} gutterBottom>
        ¿Qué estuvo mal?
      </Typography>
      <TextField
        multiline
        rows={3}
        fullWidth
        size="small"
        placeholder="Comentario opcional (máx. 500 caracteres)"
        value={comment}
        onChange={(e) => setComment(e.target.value.slice(0, 500))}
        sx={{ mb: 1.5 }}
      />
      <Box sx={{ display: "flex", gap: 1, justifyContent: "flex-end" }}>
        <Button
          size="small"
          onClick={() => void submit(false)}
          disabled={submitting}
          sx={{ color: "text.secondary" }}
        >
          Omitir
        </Button>
        <Button
          size="small"
          variant="contained"
          onClick={() => void submit(true)}
          disabled={submitting}
          sx={{ bgcolor: tokens.brand.primary, "&:hover": { bgcolor: "#0a8a78" } }}
        >
          {submitting ? <CircularProgress size={14} color="inherit" /> : "Enviar"}
        </Button>
      </Box>
    </Popover>
  );
}
