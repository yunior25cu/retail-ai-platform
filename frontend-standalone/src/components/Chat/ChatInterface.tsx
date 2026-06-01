import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Box, IconButton, Tab, Tabs, Tooltip, Typography } from "@mui/material";
import FileDownloadOutlinedIcon from "@mui/icons-material/FileDownloadOutlined";
import { tokens } from "@/theme/tokens";
import { useAuth } from "@/hooks/useAuth";
import { useChat } from "@/hooks/useChat";
import type { ChatMessage as ChatMessageType } from "@/hooks/useChat";
import { WelcomeScreen } from "./WelcomeScreen";
import { ChatMessage } from "./ChatMessage";
import { ChatInput } from "./ChatInput";
import { ContextBar } from "./ContextBar";
import { AiPinnedList } from "./AiPinnedList";
import { AiMetricsPanel } from "./AiMetricsPanel";
import { api } from "@/api/client";
import { getPins, togglePin, unpinMessage } from "@/utils/pins";
import type { PinnedMessage } from "@/utils/pins";
import { exportConversation } from "@/utils/exportHtml";

interface Props {
  externalConversationId?: string | null;
  onConversationChange?: (id: string) => void;
  onSelectConversation?: (id: string) => void;
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

export function ChatInterface({ externalConversationId, onConversationChange, onSelectConversation }: Props) {
  const { user } = useAuth();
  const {
    messages, conversationId, isLoading, error,
    suggestions, sendMessage, loadConversation, clearConversation,
  } = useChat();
  const bottomRef = useRef<HTMLDivElement>(null);
  // Metrics visible for admin roles in both verticals:
  // - direccion   → retail vertical director
  // - admin_tenant → tenant admin (produccion/other verticals)
  // - superadmin / super_admin → platform admin
  const canSeeMetrics = ["direccion", "admin_tenant", "superadmin", "super_admin"].includes(user?.role ?? "");
  const [activeTab, setActiveTab] = useState<"chat" | "pins" | "metrics">("chat");
  const [pins, setPins] = useState<PinnedMessage[]>([]);

  // Content of the pinned message we need to scroll to after conversation loads
  const [pendingScrollContent, setPendingScrollContent] = useState<string | null>(null);

  // Load pins scoped to THIS user (tenant + userId prevents cross-user leakage)
  useEffect(() => {
    if (user) setPins(getPins(user.tenant_id, user.id));
  }, [user]);

  // "Nueva conversación" — externalConversationId goes null while messages exist
  useEffect(() => {
    if (externalConversationId === null && messages.length > 0) {
      clearConversation();
      setActiveTab("chat");
      setPins(user ? getPins(user.tenant_id, user.id) : []);
    }
  }, [externalConversationId]); // eslint-disable-line react-hooks/exhaustive-deps

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
      setActiveTab("chat");
    }).catch(() => null);
  }, [externalConversationId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Notify parent when conversation ID changes
  useEffect(() => {
    if (conversationId) onConversationChange?.(conversationId);
  }, [conversationId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-scroll to bottom on new messages (only when no pin scroll is pending)
  useEffect(() => {
    if (pendingScrollContent) return;
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading, pendingScrollContent]);

  // Scroll to pinned message after the conversation finishes loading
  useEffect(() => {
    if (!pendingScrollContent || messages.length === 0) return;

    const idx = messages.findIndex(
      (m) => m.role === "assistant" && m.content.trim() === pendingScrollContent.trim()
    );

    // Clear pending regardless — if not found, nothing to scroll to
    setPendingScrollContent(null);

    if (idx === -1) return;

    // Defer until after React paints the new messages
    setTimeout(() => {
      const el = document.getElementById(`chat-msg-${idx}`);
      if (!el) return;

      el.scrollIntoView({ behavior: "smooth", block: "center" });

      // Brief highlight flash using inline style (no extra state/props needed)
      el.style.backgroundColor = `${tokens.brand.primary}22`;
      setTimeout(() => {
        el.style.backgroundColor = "";
      }, 1600);
    }, 120);
  }, [messages, pendingScrollContent]);

  const handleSend = (text: string) => {
    void sendMessage(text);
  };

  const handleTogglePin = useCallback((msg: ChatMessageType) => {
    if (!user || !conversationId) return;
    const updated = togglePin(user.tenant_id, user.id, msg, conversationId);
    setPins(updated);
  }, [user, conversationId]);

  const handleUnpin = useCallback((id: string) => {
    if (!user) return;
    const updated = unpinMessage(user.tenant_id, user.id, id);
    setPins(updated);
  }, [user]);

  // Opens the conversation containing the pin AND queues a scroll to the exact message
  const handleOpenPinnedConversation = useCallback((convId: string, content: string) => {
    setPendingScrollContent(content);
    onSelectConversation?.(convId);
    setActiveTab("chat");
  }, [onSelectConversation]);

  // Enrich messages with isPinned (keyed to this user's pins)
  const enrichedMessages = messages.map((m) => ({
    ...m,
    isPinned: user ? pins.some((p) => p.id === m.id) : false,
  }));

  return (
    <Box sx={{ height: "100%", display: "flex", flexDirection: "column", bgcolor: "#FFFFFF" }}>
      {/* Context bar */}
      {user && <ContextBar user={user} />}

      {/* Tabs: Chat / Anclados [/ Métricas] + Export button */}
      <Box sx={{ borderBottom: "1px solid", borderColor: "grey.200", px: 2, display: "flex", alignItems: "center" }}>
        <Tabs
          value={activeTab}
          onChange={(_, v: "chat" | "pins" | "metrics") => setActiveTab(v)}
          sx={{
            flex: 1, minHeight: 36,
            "& .MuiTab-root": { minHeight: 36, fontSize: "0.8rem", py: 0, textTransform: "none" },
          }}
        >
          <Tab value="chat"    label="Chat" />
          <Tab value="pins"    label={pins.length > 0 ? `Anclados (${pins.length})` : "Anclados"} />
          {canSeeMetrics && <Tab value="metrics" label="Métricas" />}
        </Tabs>
        {messages.length > 0 && activeTab === "chat" && (
          <Tooltip title="Exportar conversación">
            <IconButton
              size="small"
              onClick={() => exportConversation(messages, user?.tenant_id ?? 0)}
              sx={{ color: "text.disabled", ml: 1 }}
            >
              <FileDownloadOutlinedIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        )}
      </Box>

      {/* Tab content */}
      {activeTab === "metrics" ? (
        <Box sx={{ flex: 1, overflow: "hidden" }}>
          <AiMetricsPanel />
        </Box>
      ) : activeTab === "pins" ? (
        <Box sx={{ flex: 1, overflow: "hidden" }}>
          <AiPinnedList
            pins={pins}
            onUnpin={handleUnpin}
            onOpenConversation={handleOpenPinnedConversation}
          />
        </Box>
      ) : (
        <>
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
                {enrichedMessages.map((m, i) => (
                  <ChatMessage
                    key={m.id}
                    msg={m}
                    onTogglePin={handleTogglePin}
                    elementId={`chat-msg-${i}`}
                  />
                ))}
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
        </>
      )}
    </Box>
  );
}
