import type { ChatMessage } from "@/hooks/useChat";

export function buildConversationHtml(messages: ChatMessage[], tenantId: number): string {
  const now = new Date().toLocaleString("es-UY", {
    day: "2-digit", month: "long", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });

  const rows = messages
    .map((m) => {
      const isUser = m.role === "user";
      const time = m.timestamp.toLocaleTimeString("es-UY", { hour: "2-digit", minute: "2-digit" });
      const content = m.content
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/\n/g, "<br>");

      return `
      <div class="msg ${isUser ? "user" : "ai"}">
        <div class="bubble">${content}</div>
        <div class="meta">${isUser ? "Vos" : "Asistente IA"} · ${time}</div>
      </div>`;
    })
    .join("");

  return `<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>Conversación IA — Tenant ${tenantId}</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; max-width: 760px; margin: 40px auto; padding: 0 24px; color: #1a1a2e; }
    h1  { font-size: 1.1rem; color: #0E9F8A; border-bottom: 2px solid #0E9F8A; pb: 8px; margin-bottom: 4px; }
    .sub { font-size: 0.8rem; color: #888; margin-bottom: 32px; }
    .msg { margin-bottom: 20px; }
    .msg.user  { text-align: right; }
    .msg.ai    { text-align: left; }
    .bubble { display: inline-block; max-width: 78%; padding: 10px 14px; border-radius: 12px; font-size: 0.9rem; line-height: 1.6; white-space: pre-wrap; }
    .msg.user .bubble { background: #F4F7F9; border-radius: 18px 18px 4px 18px; }
    .msg.ai   .bubble { background: #f0faf8; border: 1px solid #d0f0eb; border-radius: 4px 18px 18px 18px; }
    .meta { font-size: 0.7rem; color: #aaa; margin-top: 4px; }
    @media print { body { margin: 20px; } }
  </style>
</head>
<body>
  <h1>Conversación — Asistente IA</h1>
  <p class="sub">Exportado el ${now} · Tenant ${tenantId} · ${messages.length} mensajes</p>
  ${rows}
</body>
</html>`;
}

export function exportConversation(messages: ChatMessage[], tenantId: number): void {
  if (messages.length === 0) return;
  const html = buildConversationHtml(messages, tenantId);
  const win = window.open("", "_blank");
  if (!win) return;
  win.document.write(html);
  win.document.close();
  win.focus();
  win.print();
}
