import { useCallback, useEffect, useState } from "react";
import type { SessionInfo, SessionStopResponse } from "../types";

const API_URL = "";

export function useSession() {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Check for active session on mount
  useEffect(() => {
    fetch(`${API_URL}/api/session/current`)
      .then((res) => res.json())
      .then((data) => {
        if (data.active && data.session) {
          setSession(data.session);
        }
      })
      .catch(() => {
        // Python API not available yet
      });
  }, []);

  const startSession = useCallback(
    async (title?: string, participants?: string[]) => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`${API_URL}/api/session/start`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: title || "",
            participants: participants || [],
          }),
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || "Failed to start session");
        }
        const data: SessionInfo = await res.json();
        setSession(data);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Unknown error");
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const stopSession = useCallback(async (): Promise<SessionStopResponse | null> => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/api/session/stop`, {
        method: "POST",
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Failed to stop session");
      }
      const data: SessionStopResponse = await res.json();
      setSession(null);
      return data;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  return {
    session,
    isActive: session !== null,
    loading,
    error,
    startSession,
    stopSession,
  };
}
