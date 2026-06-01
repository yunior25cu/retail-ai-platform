/**
 * Pin management — localStorage-based, scoped per tenant.
 * Max 10 pins per tenant.
 */

import type { ChatMessage } from "@/hooks/useChat";

const MAX_PINS = 10;

export interface PinnedMessage {
  id: string;
  content: string;
  conversationId: string;
  pinnedAt: string; // ISO string
}

function storageKey(tenantId: number) {
  return `ai_pinned_${tenantId}`;
}

export function getPins(tenantId: number): PinnedMessage[] {
  try {
    const raw = localStorage.getItem(storageKey(tenantId));
    return raw ? (JSON.parse(raw) as PinnedMessage[]) : [];
  } catch {
    return [];
  }
}

export function isPinned(tenantId: number, msgId: string): boolean {
  return getPins(tenantId).some((p) => p.id === msgId);
}

export function pinMessage(
  tenantId: number,
  msg: ChatMessage,
  conversationId: string
): PinnedMessage[] {
  const pins = getPins(tenantId);
  if (pins.some((p) => p.id === msg.id)) return pins;
  const updated = [
    { id: msg.id, content: msg.content, conversationId, pinnedAt: new Date().toISOString() },
    ...pins,
  ].slice(0, MAX_PINS);
  localStorage.setItem(storageKey(tenantId), JSON.stringify(updated));
  return updated;
}

export function unpinMessage(tenantId: number, msgId: string): PinnedMessage[] {
  const updated = getPins(tenantId).filter((p) => p.id !== msgId);
  localStorage.setItem(storageKey(tenantId), JSON.stringify(updated));
  return updated;
}

export function togglePin(
  tenantId: number,
  msg: ChatMessage,
  conversationId: string
): PinnedMessage[] {
  return isPinned(tenantId, msg.id)
    ? unpinMessage(tenantId, msg.id)
    : pinMessage(tenantId, msg, conversationId);
}
