import { useState } from "react";
import { Box } from "@mui/material";
import { AppShell } from "@/components/Layout/AppShell";
import { ChatInterface } from "@/components/Chat/ChatInterface";
import { useAuth } from "@/hooks/useAuth";

export function Chat() {
  const { user: _user } = useAuth();
  const [selectedConvId, setSelectedConvId] = useState<string | null>(null);
  const [currentConvId, setCurrentConvId] = useState<string | null>(null);

  return (
    <AppShell
      conversationId={currentConvId}
      onSelectConversation={(id) => setSelectedConvId(id)}
      onNewConversation={() => { setSelectedConvId(null); setCurrentConvId(null); }}
    >
      <Box sx={{ height: "100%" }}>
        <ChatInterface
          externalConversationId={selectedConvId}
          onConversationChange={(id) => setCurrentConvId(id)}
        />
      </Box>
    </AppShell>
  );
}
