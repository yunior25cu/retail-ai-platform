/**
 * useChat — conversation state and message sending.
 *
 * Persists conversationId in localStorage per tenant.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/api/client";
import { useAuth } from "./useAuth";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  toolsUsed?: string[];
  durationMs?: number;
}

const CONV_KEY = (tenantId: number) => `ai_conv_${tenantId}`;

export function useChat() {
  const { user } = useAuth();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  // Restore conversationId from localStorage
  useEffect(() => {
    if (!user) return;
    const saved = localStorage.getItem(CONV_KEY(user.tenant_id));
    if (saved) setConversationId(saved);
  }, [user]);

  // Load suggestions when empty
  useEffect(() => {
    if (!user || messages.length > 0) return;
    api
      .getSuggestions(user.tenant_id, user.role)
      .then((r) => setSuggestions(r.suggestions))
      .catch(() => setSuggestions([]));
  }, [user, messages.length]);

  const sendMessage = useCallback(
    async (text: string) => {
      if (!text.trim() || isLoading) return;
      setError(null);

      const userMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "user",
        content: text.trim(),
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, userMsg]);
      setSuggestions([]);
      setIsLoading(true);

      abortRef.current?.abort();
      abortRef.current = new AbortController();

      try {
        const res = await api.sendMessage({
          message: text.trim(),
          conversation_id: conversationId ?? undefined,
        });

        const assistantMsg: ChatMessage = {
          id: crypto.randomUUID(),
          role: "assistant",
          content: res.response,
          timestamp: new Date(),
          toolsUsed: res.tools_used?.map((t) => t.name),
          durationMs: res.duration_ms,
        };
        setMessages((prev) => [...prev, assistantMsg]);

        if (res.conversation_id !== conversationId) {
          setConversationId(res.conversation_id);
          if (user) {
            localStorage.setItem(CONV_KEY(user.tenant_id), res.conversation_id);
          }
        }
      } catch (err: unknown) {
        const status = (err as { response?: { status?: number } })?.response
          ?.status;
        if (status === 503) {
          setError(
            "El servicio de IA no está disponible en este momento. Intentá en unos minutos."
          );
        } else if (status === 429) {
          setError("Límite de consultas alcanzado. Esperá unos minutos.");
        } else if (status === 401) {
          setError("Sesión expirada. Por favor, iniciá sesión nuevamente.");
        } else {
          setError("Ocurrió un error. Por favor, intentá de nuevo.");
        }
      } finally {
        setIsLoading(false);
      }
    },
    [conversationId, isLoading, user]
  );

  const clearConversation = useCallback(() => {
    setMessages([]);
    setConversationId(null);
    setError(null);
    if (user) localStorage.removeItem(CONV_KEY(user.tenant_id));
  }, [user]);

  const loadConversation = useCallback(
    (convId: string, loadedMessages: ChatMessage[]) => {
      setMessages(loadedMessages);
      setConversationId(convId);
      setError(null);
      if (user) localStorage.setItem(CONV_KEY(user.tenant_id), convId);
    },
    [user]
  );

  return {
    messages,
    conversationId,
    isLoading,
    error,
    suggestions,
    sendMessage,
    clearConversation,
    loadConversation,
  };
}
