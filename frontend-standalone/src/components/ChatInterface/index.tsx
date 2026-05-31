/**
 * ChatInterface — self-contained chat UI.
 *
 * Uses MUI v7 components. Mirrors the look of the Balaxys AiAssistantDrawer
 * but calls our Python API directly via useChat().
 */

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  Divider,
  IconButton,
  InputAdornment,
  Paper,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import SendIcon from "@mui/icons-material/Send";
import AddIcon from "@mui/icons-material/Add";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import BuildOutlinedIcon from "@mui/icons-material/BuildOutlined";
import { useChat, type ChatMessage } from "@/hooks/useChat";

// ── Single message ────────────────────────────────────────────────────────────

function Message({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === "user";
  return (
    <Box
      sx={{
        display: "flex",
        justifyContent: isUser ? "flex-end" : "flex-start",
        mb: 1.5,
      }}
    >
      <Box sx={{ maxWidth: "80%" }}>
        <Paper
          elevation={0}
          sx={{
            px: 2,
            py: 1.5,
            borderRadius: isUser ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
            bgcolor: isUser ? "primary.main" : "grey.100",
            color: isUser ? "white" : "text.primary",
          }}
        >
          {isUser ? (
            <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>
              {msg.content}
            </Typography>
          ) : (
            <Box
              sx={{
                "& p": { m: 0, mb: 0.5 },
                "& ul, & ol": { pl: 2, mb: 0.5 },
                "& code": {
                  bgcolor: "grey.200",
                  px: 0.5,
                  borderRadius: 0.5,
                  fontSize: "0.8rem",
                },
                "& pre": {
                  bgcolor: "grey.200",
                  p: 1,
                  borderRadius: 1,
                  overflow: "auto",
                },
                "& strong": { fontWeight: 600 },
                "& table": { borderCollapse: "collapse", width: "100%" },
                "& th, & td": {
                  border: "1px solid",
                  borderColor: "grey.300",
                  px: 1,
                  py: 0.5,
                },
              }}
            >
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {msg.content}
              </ReactMarkdown>
            </Box>
          )}
        </Paper>

        {/* Tools used */}
        {msg.toolsUsed && msg.toolsUsed.length > 0 && (
          <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, mt: 0.5 }}>
            {msg.toolsUsed.map((t) => (
              <Chip
                key={t}
                icon={<BuildOutlinedIcon sx={{ fontSize: 12 }} />}
                label={t}
                size="small"
                variant="outlined"
                sx={{ fontSize: "0.65rem", height: 20 }}
              />
            ))}
          </Box>
        )}

        <Typography
          variant="caption"
          color="text.disabled"
          sx={{ display: "block", mt: 0.25, textAlign: isUser ? "right" : "left" }}
        >
          {msg.timestamp.toLocaleTimeString("es-UY", {
            hour: "2-digit",
            minute: "2-digit",
          })}
        </Typography>
      </Box>
    </Box>
  );
}

// ── Empty state with suggestion chips ────────────────────────────────────────

function EmptyState({
  suggestions,
  onSuggestion,
}: {
  suggestions: string[];
  onSuggestion: (s: string) => void;
}) {
  return (
    <Box
      sx={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 2,
        p: 3,
      }}
    >
      <AutoAwesomeIcon sx={{ fontSize: 48, color: "primary.light" }} />
      <Typography variant="body1" color="text.secondary" textAlign="center">
        ¿En qué puedo ayudarte hoy?
      </Typography>
      {suggestions.length > 0 && (
        <Box sx={{ display: "flex", flexDirection: "column", gap: 1, width: "100%" }}>
          {suggestions.map((s) => (
            <Chip
              key={s}
              label={s}
              onClick={() => onSuggestion(s)}
              variant="outlined"
              color="primary"
              sx={{ cursor: "pointer", justifyContent: "flex-start", height: "auto", py: 0.75 }}
            />
          ))}
        </Box>
      )}
    </Box>
  );
}

// ── Main chat interface ───────────────────────────────────────────────────────

export function ChatInterface() {
  const {
    messages,
    isLoading,
    error,
    suggestions,
    sendMessage,
    clearConversation,
  } = useChat();
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  const handleSend = () => {
    const text = input.trim();
    if (!text) return;
    setInput("");
    void sendMessage(text);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <Box
      sx={{
        height: "100%",
        display: "flex",
        flexDirection: "column",
        bgcolor: "background.paper",
      }}
    >
      {/* Header */}
      <Box
        sx={{
          px: 2,
          py: 1.5,
          display: "flex",
          alignItems: "center",
          gap: 1,
          borderBottom: 1,
          borderColor: "divider",
        }}
      >
        <AutoAwesomeIcon color="primary" />
        <Typography variant="subtitle1" fontWeight={600} sx={{ flex: 1 }}>
          IA Asistente
        </Typography>
        <Tooltip title="Nueva conversación">
          <IconButton size="small" onClick={clearConversation}>
            <AddIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Box>

      {/* Message area */}
      <Box sx={{ flex: 1, overflowY: "auto", p: 2 }}>
        {messages.length === 0 ? (
          <EmptyState suggestions={suggestions} onSuggestion={(s) => { void sendMessage(s); }} />
        ) : (
          <>
            {messages.map((m) => (
              <Message key={m.id} msg={m} />
            ))}
            {isLoading && (
              <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 1 }}>
                <CircularProgress size={16} />
                <Typography variant="caption" color="text.secondary">
                  Consultando…
                </Typography>
              </Box>
            )}
            {error && (
              <Alert severity="warning" sx={{ mb: 1 }}>
                {error}
              </Alert>
            )}
          </>
        )}
        <div ref={bottomRef} />
      </Box>

      <Divider />

      {/* Input */}
      <Box sx={{ p: 1.5 }}>
        <TextField
          fullWidth
          multiline
          maxRows={4}
          size="small"
          placeholder="Escribí tu pregunta…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isLoading}
          InputProps={{
            endAdornment: (
              <InputAdornment position="end">
                <IconButton
                  size="small"
                  color="primary"
                  onClick={handleSend}
                  disabled={isLoading || !input.trim()}
                >
                  <SendIcon fontSize="small" />
                </IconButton>
              </InputAdornment>
            ),
          }}
        />
        <Typography variant="caption" color="text.disabled" sx={{ mt: 0.5, display: "block" }}>
          Enter para enviar · Shift+Enter para nueva línea
        </Typography>
      </Box>
    </Box>
  );
}
