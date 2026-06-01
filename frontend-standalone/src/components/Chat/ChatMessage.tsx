import { useState } from "react";
import { Box, Chip, IconButton, Tooltip, Typography } from "@mui/material";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import BuildOutlinedIcon from "@mui/icons-material/BuildOutlined";
import ThumbUpOutlinedIcon from "@mui/icons-material/ThumbUpOutlined";
import ThumbUpIcon from "@mui/icons-material/ThumbUp";
import ThumbDownOutlinedIcon from "@mui/icons-material/ThumbDownOutlined";
import ThumbDownIcon from "@mui/icons-material/ThumbDown";
import PushPinOutlinedIcon from "@mui/icons-material/PushPinOutlined";
import PushPinIcon from "@mui/icons-material/PushPin";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { tokens } from "@/theme/tokens";
import type { ChatMessage as ChatMessageType } from "@/hooks/useChat";
import { api } from "@/api/client";
import { FeedbackPopover } from "./FeedbackPopover";

interface Props {
  msg: ChatMessageType;
  onTogglePin?: (msg: ChatMessageType) => void;
  elementId?: string;
}

export function ChatMessage({ msg, onTogglePin, elementId }: Props) {
  const isUser = msg.role === "user";
  const [feedbackSent, setFeedbackSent] = useState<"positive" | "negative" | null>(null);
  const [popoverAnchor, setPopoverAnchor] = useState<HTMLElement | null>(null);

  const handleThumbUp = async () => {
    if (!msg.requestId || feedbackSent) return;
    try { await api.submitFeedback({ request_id: msg.requestId, rating: "positive" }); }
    catch { /* best-effort */ }
    setFeedbackSent("positive");
  };

  const handleThumbDown = (e: React.MouseEvent<HTMLElement>) => {
    if (!msg.requestId || feedbackSent) return;
    setPopoverAnchor(e.currentTarget);
  };

  const canFeedback = !isUser && !!msg.requestId;

  return (
    <Box
      id={elementId}
      sx={{
        display: "flex",
        flexDirection: isUser ? "row-reverse" : "row",
        alignItems: "flex-start",
        gap: 1.5,
        mb: 2.5,
        maxWidth: tokens.chat.maxWidth,
        mx: "auto",
        width: "100%",
        px: 2,
        borderRadius: 2,
        transition: "background-color 0.4s ease",
      }}
    >
      {/* AI avatar */}
      {!isUser && (
        <Box
          sx={{
            width: 28, height: 28, borderRadius: "50%", flexShrink: 0,
            bgcolor: `${tokens.brand.primary}18`,
            display: "flex", alignItems: "center", justifyContent: "center",
            mt: 0.25,
          }}
        >
          <AutoAwesomeIcon sx={{ fontSize: 16, color: tokens.brand.primary }} />
        </Box>
      )}

      <Box sx={{ maxWidth: "calc(100% - 44px)", flex: 1 }}>
        {isUser ? (
          <Box
            sx={{
              display: "inline-block", ml: "auto",
              px: 2, py: 1.25, borderRadius: "18px 18px 4px 18px",
              bgcolor: tokens.chat.userMsg, maxWidth: "80%",
            }}
          >
            <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>
              {msg.content}
            </Typography>
          </Box>
        ) : (
          <Box
            sx={{
              "& p":            { m: 0, mb: 0.75, lineHeight: 1.65 },
              "& p:last-child": { mb: 0 },
              "& ul, & ol":     { pl: 2.5, mb: 0.75 },
              "& li":           { mb: 0.25 },
              "& code":         { bgcolor: "grey.100", px: 0.75, py: 0.25, borderRadius: 0.75, fontSize: "0.85em", fontFamily: "monospace" },
              "& pre":          { bgcolor: "grey.100", p: 1.5, borderRadius: 1.5, overflow: "auto", "& code": { bgcolor: "transparent", p: 0 } },
              "& strong":       { fontWeight: 600 },
              "& h1,& h2,& h3": { fontWeight: 600, mt: 1, mb: 0.5 },
              "& table":        { borderCollapse: "collapse", width: "100%", mb: 1 },
              "& th,& td":      { border: "1px solid", borderColor: "grey.300", px: 1.5, py: 0.75, fontSize: "0.875rem" },
              "& th":           { bgcolor: "grey.50", fontWeight: 600 },
              "& blockquote":   { borderLeft: `3px solid ${tokens.brand.primary}`, pl: 1.5, ml: 0, color: "text.secondary" },
              fontSize: "0.9rem", lineHeight: 1.65,
            }}
          >
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
          </Box>
        )}

        {/* Tool chips */}
        {msg.toolsUsed && msg.toolsUsed.length > 0 && (
          <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, mt: 0.75 }}>
            {msg.toolsUsed.map((t) => (
              <Chip
                key={t}
                icon={<BuildOutlinedIcon sx={{ fontSize: "11px !important" }} />}
                label={t}
                size="small"
                variant="outlined"
                sx={{ fontSize: "0.66rem", height: 20, borderColor: "grey.300", color: "text.secondary" }}
              />
            ))}
          </Box>
        )}

        {/* Footer row: timestamp + action buttons */}
        <Box sx={{ display: "flex", alignItems: "center", gap: 0.25, mt: 0.5, justifyContent: isUser ? "flex-end" : "flex-start" }}>
          <Typography
            variant="caption"
            sx={{ color: "text.disabled", mr: 0.5 }}
          >
            {msg.timestamp.toLocaleTimeString("es-UY", { hour: "2-digit", minute: "2-digit" })}
          </Typography>

          {/* Pin button — shown for all assistant messages when handler provided */}
          {!isUser && onTogglePin && (
            <Tooltip title={msg.isPinned ? "Desanclar" : "Anclar respuesta"}>
              <IconButton size="small" onClick={() => onTogglePin(msg)} sx={{ p: 0.25, color: msg.isPinned ? tokens.brand.primary : "text.disabled" }}>
                {msg.isPinned
                  ? <PushPinIcon sx={{ fontSize: 14 }} />
                  : <PushPinOutlinedIcon sx={{ fontSize: 14 }} />
                }
              </IconButton>
            </Tooltip>
          )}

          {/* Feedback buttons — only for live messages (have requestId) */}
          {canFeedback && (
            <>
              <Tooltip title={feedbackSent === "positive" ? "¡Gracias!" : "Buena respuesta"}>
                <IconButton
                  size="small"
                  onClick={() => void handleThumbUp()}
                  disabled={!!feedbackSent}
                  sx={{ p: 0.25, color: feedbackSent === "positive" ? tokens.brand.primary : "text.disabled" }}
                >
                  {feedbackSent === "positive"
                    ? <ThumbUpIcon sx={{ fontSize: 14 }} />
                    : <ThumbUpOutlinedIcon sx={{ fontSize: 14 }} />
                  }
                </IconButton>
              </Tooltip>
              <Tooltip title={feedbackSent === "negative" ? "Gracias por el feedback" : "Mala respuesta"}>
                <IconButton
                  size="small"
                  onClick={handleThumbDown}
                  disabled={!!feedbackSent}
                  sx={{ p: 0.25, color: feedbackSent === "negative" ? "error.main" : "text.disabled" }}
                >
                  {feedbackSent === "negative"
                    ? <ThumbDownIcon sx={{ fontSize: 14 }} />
                    : <ThumbDownOutlinedIcon sx={{ fontSize: 14 }} />
                  }
                </IconButton>
              </Tooltip>
            </>
          )}
        </Box>
      </Box>

      {/* Negative feedback popover */}
      {canFeedback && (
        <FeedbackPopover
          anchorEl={popoverAnchor}
          requestId={msg.requestId!}
          onClose={() => setPopoverAnchor(null)}
          onSubmitted={() => {
            setPopoverAnchor(null);
            setFeedbackSent("negative");
          }}
        />
      )}
    </Box>
  );
}
