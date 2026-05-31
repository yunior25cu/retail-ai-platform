import { useEffect, useRef } from "react";
import { Alert, Box, Typography } from "@mui/material";
import { tokens } from "@/theme/tokens";
import { useAuth } from "@/hooks/useAuth";
import { useChat } from "@/hooks/useChat";
import { WelcomeScreen } from "./WelcomeScreen";
import { ChatMessage } from "./ChatMessage";
import { ChatInput } from "./ChatInput";
import { api } from "@/api/client";

interface Props {
  externalConversationId?: string | null;
  onConversationChange?: (id: string) => void;
}

function TypingIndicator() {
  return (
    <Box sx={{ display: "flex", alignItems: "center", gap: 0.75, px: 2, mb: 1.5, maxWidth: tokens.chat.maxWidth, mx: "auto", width: "100%" }}>
      <Box sx={{ display: "flex", gap: 0.5 }}>
        {[0, 1, 2].map((i) => (
          <Box
            key={i}
            sx={{
              width: 7, height: 7, borderRadius: "50%",
              bgcolor: tokens.brand.primary,
              animation: "typing 1.2s ease-in-out infinite",
              animationDelay: `${i * 0.2}s`,
              "@keyframes typing": {
                "0%,80%,100%": { opacity: 0.3, transform: "scale(0.8)" },
                "40%":         { opacity: 1,   transform: "scale(1.1)" },
              },
            }}
          />
        ))}
      </Box>
      <Typography variant="caption" color="text.disabled">Consultando…</Typography>
    </Box>
  );
}

export function ChatInterface({ externalConversationId, onConversationChange }: Props) {
  const { user } = useAuth();
  const {
    messages, conversationId, isLoading, error,
    suggestions, sendMessage, loadConversation,
  } = useChat();
  const bottomRef = useRef<HTMLDivElement>(null);

  // Load external conversation when sidebar selection changes
  useEffect(() => {
    if (!externalConversationId || externalConversationId === conversationId) return;
    api.getConversationMessages(externalConversationId).then((msgs) => {
      const mapped = msgs.map((m, i) => ({
        id: `hist-${i}`,
        role: m.role as "user" | "assistant",
        content: m.content,
        timestamp: new Date(m.created_at),
        toolsUsed: m.tools_used ?? undefined,
        durationMs: m.duration_ms ?? undefined,
      }));
      loadConversation(externalConversationId, mapped);
    }).catch(() => null);
  }, [externalConversationId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Notify parent when conversation ID changes
  useEffect(() => {
    if (conversationId) onConversationChange?.(conversationId);
  }, [conversationId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  const handleSend = (text: string) => {
    void sendMessage(text);
  };

  return (
    <Box sx={{ height: "100%", display: "flex", flexDirection: "column", bgcolor: "#FFFFFF" }}>
      {/* Scrollable message area */}
      <Box sx={{ flex: 1, overflowY: "auto", pt: 3 }}>
        {messages.length === 0 ? (
          <WelcomeScreen
            vertical={user?.vertical ?? null}
            suggestions={suggestions}
            onSuggestion={handleSend}
          />
        ) : (
          <>
            {messages.map((m) => <ChatMessage key={m.id} msg={m} />)}
            {isLoading && <TypingIndicator />}
            {error && (
              <Box sx={{ maxWidth: tokens.chat.maxWidth, mx: "auto", px: 2, mb: 1 }}>
                <Alert severity="warning">{error}</Alert>
              </Box>
            )}
          </>
        )}
        <div ref={bottomRef} />
      </Box>

      {/* Input */}
      <ChatInput onSend={handleSend} disabled={isLoading} />
    </Box>
  );
}
