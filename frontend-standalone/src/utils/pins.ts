/**
 * Pin management — localStorage-based, scoped per user (not per tenant).
 * Key: ai_pinned_${tenantId}_${userId}   ← prevents cross-user leakage.
 * Max 10 pins per user.
 */

import type { ChatMessage } from "@/hooks/useChat";

const MAX_PINS = 10;

export interface PinnedMessage {
  id: string;
  content: string;
  conversationId: string;
  pinnedAt: string; // ISO string
}

function storageKey(tenantId: number, userId: string): string {
  return `ai_pinned_${tenantId}_${userId}`;
}

export function getPins(tenantId: number, userId: string): PinnedMessage[] {
  try {
    const raw = localStorage.getItem(storageKey(tenantId, userId));
    return raw ? (JSON.parse(raw) as PinnedMessage[]) : [];
  } catch {
    return [];
  }
}

export function isPinned(tenantId: number, userId: string, msgId: string): boolean {
  return getPins(tenantId, userId).some((p) => p.id === msgId);
}

export function pinMessage(
  tenantId: number,
  userId: string,
  msg: ChatMessage,
  conversationId: string
): PinnedMessage[] {
  const pins = getPins(tenantId, userId);
  if (pins.some((p) => p.id === msg.id)) return pins;
  const updated = [
    { id: msg.id, content: msg.content, conversationId, pinnedAt: new Date().toISOString() },
    ...pins,
  ].slice(0, MAX_PINS);
  localStorage.setItem(storageKey(tenantId, userId), JSON.stringify(updated));
  return updated;
}

export function unpinMessage(tenantId: number, userId: string, msgId: string): PinnedMessage[] {
  const updated = getPins(tenantId, userId).filter((p) => p.id !== msgId);
  localStorage.setItem(storageKey(tenantId, userId), JSON.stringify(updated));
  return updated;
}

export function togglePin(
  tenantId: number,
  userId: string,
  msg: ChatMessage,
  conversationId: string
): PinnedMessage[] {
  return isPinned(tenantId, userId, msg.id)
    ? unpinMessage(tenantId, userId, msg.id)
    : pinMessage(tenantId, userId, msg, conversationId);
}
