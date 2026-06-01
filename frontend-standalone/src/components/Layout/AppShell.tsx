import { useState } from "react";
import { Box, Drawer, IconButton, useMediaQuery, useTheme } from "@mui/material";
import MenuIcon from "@mui/icons-material/Menu";
import { tokens } from "@/theme/tokens";
import { Sidebar } from "@/components/Sidebar/Sidebar";

interface Props {
  conversationId?: string | null;
  onSelectConversation?: (id: string) => void;
  onNewConversation?: () => void;
  children: React.ReactNode;
}

const SIDEBAR_W = tokens.sidebar.width;

export function AppShell({ conversationId = null, onSelectConversation = () => {}, onNewConversation = () => {}, children }: Props) {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("md"));
  const [mobileOpen, setMobileOpen] = useState(false);

  const sidebar = (
    <Sidebar
      conversationId={conversationId}
      onSelectConversation={(id) => {
        onSelectConversation(id);
        setMobileOpen(false);
      }}
      onNewConversation={() => {
        onNewConversation();
        setMobileOpen(false);
      }}
    />
  );

  return (
    <Box sx={{ display: "flex", height: "100vh", overflow: "hidden" }}>
      {/* Desktop sidebar */}
      {!isMobile && (
        <Box sx={{ width: SIDEBAR_W, flexShrink: 0 }}>{sidebar}</Box>
      )}

      {/* Mobile drawer */}
      {isMobile && (
        <Drawer
          open={mobileOpen}
          onClose={() => setMobileOpen(false)}
          PaperProps={{ sx: { width: SIDEBAR_W, bgcolor: tokens.sidebar.bg } }}
        >
          {sidebar}
        </Drawer>
      )}

      {/* Main area */}
      <Box sx={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {/* Mobile hamburger */}
        {isMobile && (
          <Box sx={{ px: 1, py: 0.5, borderBottom: 1, borderColor: "divider", bgcolor: tokens.sidebar.bg }}>
            <IconButton onClick={() => setMobileOpen(true)} sx={{ color: "white" }}>
              <MenuIcon />
            </IconButton>
          </Box>
        )}
        <Box sx={{ flex: 1, overflow: "hidden" }}>{children}</Box>
      </Box>
    </Box>
  );
}
