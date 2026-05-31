import { Box, Chip, Typography } from "@mui/material";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import BuildOutlinedIcon from "@mui/icons-material/BuildOutlined";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { tokens } from "@/theme/tokens";
import type { ChatMessage as ChatMessageType } from "@/hooks/useChat";

interface Props {
  msg: ChatMessageType;
}

export function ChatMessage({ msg }: Props) {
  const isUser = msg.role === "user";
  return (
    <Box
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

        <Typography
          variant="caption"
          sx={{ display: "block", mt: 0.5, color: "text.disabled", textAlign: isUser ? "right" : "left" }}
        >
          {msg.timestamp.toLocaleTimeString("es-UY", { hour: "2-digit", minute: "2-digit" })}
        </Typography>
      </Box>
    </Box>
  );
}
