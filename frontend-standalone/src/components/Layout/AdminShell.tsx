import { useState } from "react";
import { Box, Drawer, IconButton, useMediaQuery, useTheme } from "@mui/material";
import MenuIcon from "@mui/icons-material/Menu";
import { tokens } from "@/theme/tokens";
import { AdminSidebar } from "@/components/Sidebar/AdminSidebar";

/**
 * Layout shell for the super-admin section.
 *
 * Same chrome as AppShell (desktop fixed sidebar + mobile drawer) but mounts
 * AdminSidebar instead of the chat Sidebar and does NOT carry conversation
 * props. Used by every /admin/* route.
 */

interface Props {
  children: React.ReactNode;
}

const SIDEBAR_W = tokens.sidebar.width;

export function AdminShell({ children }: Props) {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("md"));
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <Box sx={{ display: "flex", height: "100vh", overflow: "hidden" }}>
      {/* Desktop sidebar */}
      {!isMobile && (
        <Box sx={{ width: SIDEBAR_W, flexShrink: 0 }}>
          <AdminSidebar />
        </Box>
      )}

      {/* Mobile drawer */}
      {isMobile && (
        <Drawer
          open={mobileOpen}
          onClose={() => setMobileOpen(false)}
          PaperProps={{ sx: { width: SIDEBAR_W, bgcolor: tokens.sidebar.bg } }}
        >
          <Box onClick={() => setMobileOpen(false)} sx={{ height: "100%" }}>
            <AdminSidebar />
          </Box>
        </Drawer>
      )}

      {/* Main area */}
      <Box sx={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {isMobile && (
          <Box sx={{ px: 1, py: 0.5, borderBottom: 1, borderColor: "divider", bgcolor: tokens.sidebar.bg }}>
            <IconButton onClick={() => setMobileOpen(true)} sx={{ color: "white" }}>
              <MenuIcon />
            </IconButton>
          </Box>
        )}
        <Box sx={{ flex: 1, overflow: "auto" }}>{children}</Box>
      </Box>
    </Box>
  );
}
