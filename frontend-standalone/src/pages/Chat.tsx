import { useState } from "react";
import { Box } from "@mui/material";
import { AppShell } from "@/components/Layout/AppShell";
import { ChatInterface } from "@/components/Chat/ChatInterface";
import { useAuth } from "@/hooks/useAuth";

export function Chat() {
  const { user: _user } = useAuth();
  const [selectedConvId, setSelectedConvId] = useState<string | null>(null);
  const [currentConvId, setCurrentConvId] = useState<string | null>(null);
  // Bumped on every "Nueva conversación" click so ChatInterface can reset
  // unconditionally — see comment on the Props.newConvSignal field.
  const [newConvSignal, setNewConvSignal] = useState(0);

  return (
    <AppShell
      conversationId={currentConvId}
      onSelectConversation={(id) => setSelectedConvId(id)}
      onNewConversation={() => {
        setSelectedConvId(null);
        setCurrentConvId(null);
        setNewConvSignal((n) => n + 1);
      }}
    >
      <Box sx={{ height: "100%" }}>
        <ChatInterface
          externalConversationId={selectedConvId}
          newConvSignal={newConvSignal}
          onConversationChange={(id) => setCurrentConvId(id)}
          onSelectConversation={(id) => setSelectedConvId(id)}
        />
      </Box>
    </AppShell>
  );
}
