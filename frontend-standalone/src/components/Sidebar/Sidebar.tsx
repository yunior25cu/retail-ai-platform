import { useCallback, useEffect, useState } from "react";
import {
  Avatar, Box, Button, IconButton, List, ListItemButton,
  ListItemText, Tooltip, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import LogoutIcon from "@mui/icons-material/Logout";
import AdminPanelSettingsOutlinedIcon from "@mui/icons-material/AdminPanelSettingsOutlined";
import { useNavigate } from "react-router-dom";
import { tokens } from "@/theme/tokens";
import { api, type ConversationSummary } from "@/api/client";
import { useAuth } from "@/hooks/useAuth";

interface Props {
  conversationId: string | null;
  onSelectConversation: (id: string) => void;
  onNewConversation: () => void;
}

function groupByDate(convs: ConversationSummary[]) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today); yesterday.setDate(yesterday.getDate() - 1);
  const weekAgo   = new Date(today); weekAgo.setDate(weekAgo.getDate() - 7);

  const groups: Record<string, ConversationSummary[]> = {
    "Hoy": [], "Ayer": [], "Esta semana": [], "Más antiguas": [],
  };

  for (const c of convs) {
    const d = c.last_message_at ? new Date(c.last_message_at) : new Date(0);
    const day = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    if (day >= today)        groups["Hoy"].push(c);
    else if (day >= yesterday) groups["Ayer"].push(c);
    else if (day >= weekAgo)   groups["Esta semana"].push(c);
    else                       groups["Más antiguas"].push(c);
  }
  return groups;
}

const sx = {
  root: {
    width: tokens.sidebar.width, flexShrink: 0, display: "flex",
    flexDirection: "column", height: "100%",
    bgcolor: tokens.sidebar.bg, color: tokens.sidebar.text,
  },
  logo: { px: 2, py: 2, display: "flex", alignItems: "center", gap: 1 },
  newBtn: {
    mx: 1.5, mb: 1, justifyContent: "flex-start", gap: 1,
    color: tokens.sidebar.text,
    border: `1px solid rgba(255,255,255,0.2)`,
    borderRadius: 2, textTransform: "none",
    "&:hover": { bgcolor: tokens.sidebar.hover },
  },
  groupLabel: {
    px: 2, pt: 1.5, pb: 0.5, fontSize: "0.7rem", fontWeight: 600,
    color: tokens.sidebar.textMuted, textTransform: "uppercase" as const, letterSpacing: 1,
  },
  convItem: (active: boolean) => ({
    borderRadius: 1.5, mx: 0.5, mb: 0.25,
    bgcolor: active ? tokens.sidebar.active : "transparent",
    "&:hover": { bgcolor: tokens.sidebar.hover },
    "&:hover .del-btn": { visibility: "visible" },
    color: tokens.sidebar.text,
  }),
  footer: {
    mt: "auto", px: 1.5, py: 1.5,
    borderTop: `1px solid rgba(255,255,255,0.1)`,
  },
};

export function Sidebar({ conversationId, onSelectConversation, onNewConversation }: Props) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);

  const loadConversations = useCallback(() => {
    api.getConversations().then(setConversations).catch(() => null);
  }, []);

  useEffect(() => { loadConversations(); }, [loadConversations]);

  // Refresh list when active conversation changes (new conversation created)
  useEffect(() => { if (conversationId) loadConversations(); }, [conversationId]); // eslint-disable-line react-hooks/exhaustive-deps

  const groups = groupByDate(conversations);
  const canConfig = user && ["super_admin", "superadmin", "admin_tenant", "direccion"].includes(user.role);
  const canAdmin  = user && ["super_admin", "superadmin"].includes(user.role);

  return (
    <Box sx={sx.root}>
      {/* Logo */}
      <Box sx={sx.logo}>
        <AutoAwesomeIcon sx={{ color: tokens.brand.primary, fontSize: 22 }} />
        <Typography variant="subtitle1" fontWeight={700}>
          IA Asistente
        </Typography>
      </Box>

      {/* New conversation */}
      <Button startIcon={<AddIcon />} sx={sx.newBtn} onClick={onNewConversation} fullWidth>
        Nueva conversación
      </Button>

      {/* Conversation list */}
      <Box sx={{ flex: 1, overflowY: "auto", pb: 1 }}>
        {Object.entries(groups).map(([label, items]) =>
          items.length === 0 ? null : (
            <Box key={label}>
              <Typography sx={sx.groupLabel}>{label}</Typography>
              <List dense disablePadding>
                {items.map((c) => (
                  <ListItemButton
                    key={c.conversation_id}
                    selected={c.conversation_id === conversationId}
                    onClick={() => onSelectConversation(c.conversation_id)}
                    sx={sx.convItem(c.conversation_id === conversationId)}
                  >
                    <ListItemText
                      primary={c.title || "Conversación"}
                      primaryTypographyProps={{
                        noWrap: true, fontSize: "0.82rem",
                        color: tokens.sidebar.text,
                      }}
                    />
                    <IconButton
                      className="del-btn"
                      size="small"
                      sx={{ visibility: "hidden", color: tokens.sidebar.textMuted, p: 0.25 }}
                      onClick={(e) => {
                        e.stopPropagation();
                        setConversations((prev) =>
                          prev.filter((x) => x.conversation_id !== c.conversation_id)
                        );
                      }}
                    >
                      <DeleteOutlineIcon fontSize="small" />
                    </IconButton>
                  </ListItemButton>
                ))}
              </List>
            </Box>
          )
        )}
      </Box>

      {/* Footer */}
      <Box sx={sx.footer}>
        <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 1 }}>
          <Avatar sx={{ width: 28, height: 28, bgcolor: tokens.brand.primary, fontSize: 12 }}>
            {user?.email?.[0]?.toUpperCase() ?? "?"}
          </Avatar>
          <Typography
            variant="caption" noWrap
            sx={{ flex: 1, color: tokens.sidebar.textMuted }}
          >
            {user?.email}
          </Typography>
        </Box>
        <Box sx={{ display: "flex", gap: 0.5 }}>
          {canConfig && (
            <Tooltip title="Configuración">
              <IconButton size="small" sx={{ color: tokens.sidebar.textMuted }}
                onClick={() => navigate("/configuracion")}>
                <SettingsOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          )}
          {canAdmin && (
            <Tooltip title="Administración">
              <IconButton size="small" sx={{ color: tokens.sidebar.textMuted }}
                onClick={() => navigate("/admin")}>
                <AdminPanelSettingsOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          )}
          <Tooltip title="Cerrar sesión">
            <IconButton size="small" sx={{ color: tokens.sidebar.textMuted }}
              onClick={() => { void logout(); }}>
              <LogoutIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Box>
      </Box>
    </Box>
  );
}
